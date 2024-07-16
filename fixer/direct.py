from common.handles import LANGUAGE_MODEL, REPO
from fixer.module import make_code_index
from fixer.public_search import PUBLIC_SEARCH
from fixer.auxiliary_search import AUX_SEARCH
from fixer.golden_retriever import GOLDEN_RETRIEVER
from datasets import load_dataset

import typing as t
import time
import json
from enum import Enum

DIRECT_FIX_SYSTEM_MSG = """
Based on a github issue and on helpful auxiliary information, you will help me fix a bug in a codebase.

To fix the bug, you will generate patches in the unified diff format. For example, to change line 5 from "old code" to "new code" in `file.py`, you would write:
```diff
--- a/file.py
+++ b/file.py
@@ -5,1 +5,1 @@
-old code
+new code
```
Remember than line number are 1-indexed and inclusive.
"""

DIRECT_FIX_INSTRUCTIONS = """
Generate a patch that fixes the github issue.


Format you response as follows:
<reason>
```md
# Overall explanation of the changes you made.
```
</reason>

<patch>
```diff
# Patch. Make sure to include the full patch, including the headers.
```
</patch>

Here are hard requirements:
- Make sure you respect the block names (reason, patch, etc.) and the diff code block format.
- When using an auxiliary function from another file, import it INSIDE the block of code that uses it. This is to prevent circular imports.

Here are some general tips:
- Be very careful with error messages:
    - Generally do not modify then, unless very explicitly asked to. Otherwise, it can break existing tests.
    - When explicitly asked to, try to use the exact error message provided if any.
"""


class DirectFixer:
    def __init__(self, specific_instance_ids=None, check_cache=True):
        config = LANGUAGE_MODEL.config
        working_stage = config["working_stage"]
        dataset_name = config["dataset"]
        split = config["split"]
        num_shards = config.get("num_shards", None)
        shard_id = config.get("shard_id", None)
        dataset = load_dataset(dataset_name, split=split)
        if shard_id is not None:
            dataset = dataset.shard(num_shards, shard_id)
        self.instance_items = {}
        for item in dataset:
            instance_id = item["instance_id"]
            if specific_instance_ids is not None and instance_id not in specific_instance_ids:
                continue
            self.instance_items[instance_id] = item
        self.check_cache = check_cache
        self.result_file = f"{working_stage}/direct_fixes.jsonl"

    def make_fix(self, instance_id: str):
        item = self.instance_items[instance_id]
        issue = item["problem_statement"]
        repo = item["repo"]
        code_index = make_code_index(item, check_cache=self.check_cache)
        fix_context = GOLDEN_RETRIEVER.retrieve_fix_context(code_index)
        print(f"Fix context:\n{fix_context}")
        aux_context = AUX_SEARCH.perform_aux_search(code_index)
        print(f"Aux context:\n{aux_context}")
        print(f"Fix context length: {len(fix_context)}")
        print(f"Aux context length: {len(aux_context)}")
        prompt = f"""
Repository: {repo}
---
Start of issue:
{issue}
End of issue.
---
{fix_context}
{aux_context}
---

Your task: {DIRECT_FIX_INSTRUCTIONS}
"""
        cache_key = f"direct_fix_{instance_id}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=DIRECT_FIX_SYSTEM_MSG, cache_key=cache_key)
        print(f"Response:\n{response}")
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="patch", code_lang="diff")
        if len(codes) == 0:
            return ""
        return codes["patch"]



    def make_fixes(self):
        with open(self.result_file, "w") as f:
            for instance_id, item in self.instance_items.items():
                patch = self.make_fix(instance_id)
                patch = REPO.explore_valid_patch(item, patch)
                if patch is not None:
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
                    "model_name_or_path": LANGUAGE_MODEL.llm.value,
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