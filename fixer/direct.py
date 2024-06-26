from . import Fixer
from common.interfaces import FileDisplayLevel, RetrievedFile
from retrieval import Retriever
from common import call_llm, bcolors, TokenLimitException, RateLimitException
import typing as t
import time
import unidiff
import json
from enum import Enum
from swebench.harness.utils import extract_minimal_patch
import dotenv, os
import git

dotenv.load_dotenv()
github_token = os.getenv("GITHUB_TOKEN")


class PromptingStrategy(Enum):
    ONE_SHOT_CODE_ONLY = "one_code_only"
    ONE_SHOT_WITH_TESTS = "one_code_with_tests"




class DirectFix:
    def __init__(self, overall_reasoning: str, reasonings: t.List[str], codeblocks: t.List[str], block_attrs: t.List[t.Dict[str, str]]):
        self.overall_reasoning = overall_reasoning
        self.edits = []
        for (reasoning, codeblock, block_attr) in zip(reasonings, codeblocks, block_attrs):
            reasoning = reasoning if reasoning is not None else ""
            codeblock = codeblock if codeblock is not None else ""
            # This order of replacements is important
            possible_surroundings = ["```diff, ```py", "```md", "```\n", "\n```"]
            for s in possible_surroundings:
                codeblock = codeblock.replace(s, "```")
                reasoning = reasoning.replace(s, "```")
            codeblock = codeblock.replace("```", "")
            reasoning = reasoning.replace("```", "")
            codeblock = extract_minimal_patch(codeblock)
            self.edits.append({
                "codeblock": codeblock,
                "reasoning": reasoning
            })
        self.final_patch = None

    def to_patch(self):
        """Convert the fix to a patch."""
        patch_str = "\n".join(edit["codeblock"] for edit in self.edits)
        return patch_str

    def check_patch(self, repo, abs_patch_path, patch, commit, relaxed):
        print(f"Checking patch:\n{patch}")
        with open(abs_patch_path, "w") as f:
            f.write(patch)
        try:
            if relaxed:
                repo.git.apply(abs_patch_path, "-v", "--unidiff-zero", "--whitespace=fix")
            else:
                repo.git.apply(abs_patch_path, "-v")
            final_patch = repo.git.diff()
        except Exception as e:
            print(f"Failing patch: {e}")
            final_patch = None
        repo.git.reset("--hard", commit)
        return final_patch


    def check_validity_aux(self, repo, commit, download_dir, patch):
        # Reset the repo to the commit
        owner, repo_name = repo.split("/")
        repo_url = f"https://{github_token}@github.com/{owner}/{repo_name}.git"
        repo_target = f"{download_dir}/{owner}__{repo_name}"
        print(f"Reset {owner}/{repo_name} to commit {commit}")
        repo = git.Repo(repo_target)
        repo.git.reset("--hard", commit)
        repo.git.clean("-fdxq")
        # Try to apply the patch
        patch_file = f"working_stage/check__{owner}__{repo_name}__{commit}.patch"
        abs_path = os.path.abspath(patch_file)
        print("Relaxed Check...")
        final_patch = self.check_patch(repo, abs_path, patch, commit, True)
        if final_patch is None:
            return False
        print("Strict Check...")
        ok = self.check_patch(repo, abs_path, final_patch, commit, False)
        if ok is None:
            print("Retrying with EOL...")
            final_patch += "\n"
            ok = self.check_patch(repo, abs_path, final_patch, commit, False)
        if ok is None:
            return False
        print(f"Passed all checks!")
        self.final_patch = final_patch
        return True

    def remove_whitespace(self, patch):
        from_str, to_str = "\n\n@@", "\n@@"
        while from_str in patch:
            patch = patch.replace(from_str, to_str)
        return patch


    def check_validity(self, repo, commit, download_dir):
        default_patch = self.to_patch()
        minimal_patch = extract_minimal_patch(default_patch)
        default_no_whitespace = self.remove_whitespace(default_patch)
        minimal_no_whitespace = self.remove_whitespace(minimal_patch)
        possibilities = [
            ("default", default_patch),
            ("minimal", minimal_patch),
            ("default_no_whitespace", default_no_whitespace),
            ("minimal_no_whitespace", minimal_no_whitespace),
        ]
        for name, patch in possibilities:
            print(f"Checking {name}...")
            if self.check_validity_aux(repo, commit, download_dir, patch):
                return True
        return False
        
    


class DirectFixer(Fixer):
    def __init__(self, retriever: Retriever, load_cache=True, verbose=False, prompting_strategy=PromptingStrategy.ONE_SHOT_CODE_ONLY):
        self.prompting_strategy = prompting_strategy
        fixer_name = f"direct{prompting_strategy.value}"
        super().__init__(fixer_name, retriever, load_cache=load_cache, verbose=verbose)
        direct_config = self.retriever.config["direct"]
        self.test_output_instructions = direct_config["test_output_instructions"].strip()
        self.test_task_instructions = direct_config["test_task_instructions"].strip()
        self.code_task_instructions = direct_config["code_task_instructions"].strip()
        self.code_output_instructions = direct_config["code_output_instructions"].strip()
        self.specific_instances = direct_config.get("specific_instances", None)
        if self.cached_data is not None:
            self.fixes, self.prompts = self.cached_data
        else:
            self.fixes: t.Dict[str, DirectFix] = {}
            self.prompts: t.Dict[str, str] = {}

        # # For testing
        # overall_explanation, explanations, codeblocks, attrs = self.parse_code_response(test_resp)
        # fix = DirectFix(overall_explanation, explanations, codeblocks, attrs)
        # valid = fix.check_validity("sqlfluff/sqlfluff", "14e1a23a3166b9a645a16de96f694c77a5d4abb7", self.retriever.repo_download_dir)
        # exit(0)
        for item in self.retriever.dataset:
            instance_id = item["instance_id"]
            if self.specific_instances is not None and instance_id not in self.specific_instances:
                continue
            # First try long prompt, then the shorter prompt in case the token limit is reached.
            long_prompt = self.make_prompt_for_edits(item, shorten=False)
            short_prompt = self.make_prompt_for_edits(item, shorten=True)
            # Check cache.
            cached_prompt = self.prompts.get(instance_id, None)
            cached_fix = self.fixes.get(instance_id, None)
            if cached_fix is not None and (cached_prompt == long_prompt or cached_prompt == short_prompt):
                print(f"Skipping {instance_id}...")
                continue
            print(f"Processing {instance_id}...")
            self.fixes[instance_id] = None
            self.prompts[instance_id] = None
            for prompt in [long_prompt, short_prompt]:
                try:
                    # Try until a valid fix is obtained.
                    valid = False
                    for _ in range(5):
                        overall_explanation, explanations, codeblocks, attrs = self.prompt_and_parse(prompt)
                        fix = DirectFix(overall_explanation, explanations, codeblocks, attrs)
                        valid = fix.check_validity(item["repo"], item["base_commit"], self.retriever.repo_download_dir)
                        if valid:
                            break
                    if valid:
                        self.fixes[instance_id] = fix
                        print(self.fixes[instance_id].to_patch())
                        self.prompts[instance_id] = prompt
                        print(self.format_for_context(instance_id))
                    else:
                        self.fixes[instance_id] = None
                        self.prompts[instance_id] = None
                        print(f"{bcolors.FAIL}Failed to obtain a valid fix for {instance_id}.{bcolors.ENDC}")
                        exit(0)
                    break
                except TokenLimitException as _e:
                    print(f"{bcolors.WARNING}Token limit reached for {instance_id}. Retrying with shorter prompt...{bcolors.ENDC}")
                    continue
            # Save to cache
            self.save_to_cache((self.fixes, self.prompts))

    def get_test_context(self, instance_id: str):
        """Make prompt for deriving info from the test cases"""
        if self.prompting_strategy == PromptingStrategy.ONE_SHOT_CODE_ONLY:
            test_context = None
        elif self.prompting_strategy == PromptingStrategy.ONE_SHOT_WITH_TESTS:
            test_context = self.retriever.format_tests_for_context(instance_id)
        if test_context is None or test_context == "":
            return ""
        return f"""
---
Here is information about the tests that the fix should pass:
{test_context}
---
"""

    def make_prompt_for_edits(self, item, shorten=False):
        """Make a basic prompt for the given item."""
        repo = item["repo"]
        issue = item["problem_statement"]
        instance_id = item["instance_id"]
        test_context = self.get_test_context(instance_id)
        injection = self.injections.get(instance_id, "")
        if shorten:
            # TODO: Replace with smarter summary + lines.
            display_level = FileDisplayLevel.LINES_ONLY
        else:
            display_level = FileDisplayLevel.FILE_AND_LINES
        retrieval_context = self.retriever.format_for_context(instance_id, display_level=display_level)
        prompt = f"""
---
Repository: {repo}
---
Here is the issue:
Start of issue:
{issue}
End of issue.
---
{retrieval_context}
{test_context}
---
{injection}
---
Your task: {self.code_task_instructions}

{self.code_output_instructions}

        """.strip()
        return prompt
    
    def parse_block(self, output: str, tag: str):
        """Parse code between <tag attrs> and </tag>"""
        start_tag = f"<{tag}"
        end_tag = f"</{tag}>"
        start = output.find(start_tag)
        if start == -1:
            return None
        # Parse attributes: attr1=value1 attr2=value2
        attrs_start = start + len(start_tag)
        attrs_end = output.find(">", attrs_start)
        attrs = output[attrs_start:attrs_end]
        attrs = attrs.split(" ")
        attrs = {a.split("=")[0]: a.split("=")[1] for a in attrs if "=" in a}
        # Parse content
        start_block = attrs_end + 1
        end_block = output.find(end_tag, start_block)
        block = output[start_block:end_block]
        if block.startswith("\n"):
            block = block[1:]
        if block.endswith("\n"):
            block = block[:-1]
        return block, attrs


    def prompt_and_parse(self, prompt: str, attempts=1):
        """Call LLM and parse the response."""
        try:
            response = call_llm(prompt, self.llm_type, verbose=self.verbose)
        except RateLimitException as e:
            if attempts >= self.retriever.config["max_llm_attempts"]:
                print(f"{bcolors.FAIL}Max attempts failed: {attempts}.{bcolors.ENDC}")
                raise e
            print(f"{bcolors.WARNING}Throttling detected. Waiting 1min and retrying...{bcolors.ENDC}")
            time.sleep(60)
            return self.prompt_and_parse(prompt, attempts=attempts+1)
        # For testing
        return self.parse_code_response(response)

    def parse_code_response(self, response: str):
        overall_explanation, _ = self.parse_block(response, "mdblock")
        explanations = []
        codeblocks = []
        attrs = []
        try:
            codeblock, block_attrs = self.parse_block(response, f"patch")
            explanations.append(explanation)
            codeblocks.append(codeblock)
            attrs.append(block_attrs)
        except:
            pass
        i = 1
        while True:
            try:
                explanation, _ = self.parse_block(response, f"mdblock{i}")
            except:
                explanation = None
            try:
                codeblock, block_attrs = self.parse_block(response, f"patch{i}")
                explanations.append(explanation)
                codeblocks.append(codeblock)
                attrs.append(block_attrs)
                i += 1
            except:
                break
        return overall_explanation, explanations, codeblocks, attrs

    def format_for_context(self, instance_id: str) -> str:
        """Format the fixes for the given id."""
        fix = self.fixes[instance_id]
        if fix is None:
            return None
        overall_reasoning = fix.overall_reasoning
        snippets = []
        for edit in fix.edits:
            codeblock = edit["codeblock"]
            reasoning = edit["reasoning"]
            if reasoning is None:
                reasoning = ""
            else:
                reasoning = f"Reasoning:\n{reasoning}"
            snippet = f"""
{reasoning}
Patch:
```diff
{codeblock}
```
""".strip()
            snippets.append(snippet)
        snippets = "\n------\n".join(snippets)
        return f"""
Overall reasoning:
{overall_reasoning}

Code changes:
{snippets}
"""


    def serialize_all(self):
        # Remove .pkl extension
        metadata = {
            "model_name_or_path": self.llm_type.value,
        }
        with open(self.result_file, "w") as f:
            for item in self.retriever.dataset:
                instance_id = item["instance_id"]
                fix = self.fixes.get(instance_id, None)
                if self.specific_instances is not None and instance_id not in self.specific_instances:
                    continue
                if fix is not None:
                    fix.check_validity(item["repo"], item["base_commit"], self.retriever.repo_download_dir)
                    patch = fix.final_patch
                    test_file = f"working_stage/essai-fix-{instance_id}.patch"
                    with open(test_file, "w") as tf:
                        tf.write(patch)
                else:
                    patch = ""
                    raise ValueError(f"Fix for {instance_id} is None.")
                print(f"Serializing {instance_id}:\n{patch}")
                res = {
                    "instance_id": instance_id,
                    "model_patch": patch,
                    "model_name_or_path": self.llm_type.value,
                }
                res = json.dumps(res)
                f.write(res + "\n")
        print(f"Serialized fixes to {self.result_file}")



test_instance_id = "sqlfluff__sqlfluff-1625"
test_resp = """
Here are the changes to fix the issue:

<mdblock>
```md
The issue is that the rule is incorrectly triggering "Avoid using aliases in join condition" when there is no join present. The rule should only check for aliases in join conditions, not for aliases in general.

To fix this, we need to modify the rule description to clarify it only applies to join conditions. We also need to change the violation description to match.
```
</mdblock>

<mdblock1>
```md
Update the rule docstring to clarify it only applies to aliases in join conditions, not aliases in general.
```
</mdblock1>

<patch1>
```diff
--- a/src/sqlfluff/rules/L031.py
+++ b/src/sqlfluff/rules/L031.py
@@ -10,7 +10,7 @@
 
 
 @document_fix_compatible
-class Rule_L031(BaseRule):
+class Rule_L031(BaseRule):
     \"""Avoid table aliases in from clauses and join conditions.
 
     | **Anti-pattern**
@@ -25,7 +25,7 @@
 
 
     | **Best practice**
-    |  Avoid aliases.
+    |  Avoid aliases in join conditions.
 
     .. code-block:: sql
 
@@ -45,6 +45,8 @@
             table
             LEFT JOIN table AS table_alias ON table.foreign_key = table_alias.foreign_key
 
+    Aliases are allowed in FROM clauses, but not in JOIN conditions.
+
     \"""
 
     def _eval(self, segment, **kwargs):
```
</patch1>

<mdblock2>
```md
Update the violation description to match the updated rule description. It should specify the violation is for aliases in join conditions.
```
</mdblock2>

<patch2>
```diff
--- a/src/sqlfluff/rules/L031.py
+++ b/src/sqlfluff/rules/L031.py
@@ -214,1 +214,1 @@
-                    description="Avoid using aliases in join condition",
+                    description="Avoid using table aliases in join conditions",
```
</patch2>

This should resolve the issue by clarifying the rule only flags table aliases used in join conditions as violations, not all aliases. Aliases are still allowed in FROM clauses. The updated descriptions make it clear when the rule applies.
"""