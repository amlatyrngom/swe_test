from .code_search import CodeSearch
import typing as t
from common.handles import LANGUAGE_MODEL
from common.browser.module import CodeDisplayLevel, LineNumberMode
import tomllib
import json


class DirSelection:
    def __init__(self):
        selection_config = tomllib.load(open("configs/dir_selection.toml", "rb"))
        self.system_msg = selection_config["system_msg"]
        self.top_level_instructions = selection_config["top_level_instructions"]
        self.refinement_instructions = selection_config["refinement_instructions"]
        self.subsystem = "dir_selection"
        self.narrowing_system_msg = selection_config["narrowing_system_msg"]
        self.narrowing_instructions = selection_config["narrowing_instructions"]
        self.final_selection_system_msg = selection_config["final_selection_system_msg"]
        self.final_selection_instructions = selection_config["final_selection_instructions"]
    

    def find_top_level_dirs(self, item: t.Dict[str, t.Any], code_search: CodeSearch) -> t.List[str]:
        instance_id = item["instance_id"]
        issue = item["problem_statement"]
        repo = item["repo"]
        dirs = code_search.get_dirs(max_depth=0)
        dirs = "\n".join(dirs)
        prompt = f"""
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---
Here are the top-level directories in the repo:
{dirs}
---
Your task: {self.top_level_instructions}
"""
        cache_key = f"{self.subsystem}_top_level_{instance_id}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=self.system_msg, cache_key=cache_key)
        _reasons, codes, _attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="dirs", code_lang="json")
        assert len(codes) == 1
        code = codes["dirs"].strip()
        print(f"Code: {code}")
        code = json.loads(code)
        return code["relevant"]
    

    def refine_files(self, item: t.Dict[str, t.Any], code_search: CodeSearch, candidates: t.List[t.Tuple[str, int]]) -> t.List[str]:
        instance_id = item["instance_id"]
        issue = item["problem_statement"]
        repo = item["repo"]
        candidates = "\n".join([f"Rank {rank}: {filename}" for filename, rank in candidates])
        prompt = f"""
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---
Here are the candidates for relevant files:
{candidates}
---
{self.refinement_instructions}
"""
        cache_key = f"{self.subsystem}_refinement_{instance_id}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=self.system_msg, cache_key=cache_key)
        _reasons, codes, _attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="files", code_lang="json")
        assert len(codes) == 1
        code = codes["files"].strip()
        code = json.loads(code)
        return code["relevant"]
    
    def narrow_down_result(self, item: t.Dict[str, t.Any], code_search: CodeSearch, search_result: t.Dict[str, t.Any]):
        instance_id = item["instance_id"]
        issue = item["problem_statement"]
        repo = item["repo"]
        filename = search_result['filename']
        elem_type = search_result['elem_type']
        matching_module = code_search.modules[filename]
        if elem_type == 'function':
            fn_name = search_result['elem_name']
            matching_subcontent = matching_module.display_function(fn_name, CodeDisplayLevel.FULL, LineNumberMode.ENABLED)
        elif elem_type == 'method':
            class_name = search_result['parent_name']
            method_name = search_result['elem_name']
            matching_subcontent = matching_module.display_method(class_name, method_name, CodeDisplayLevel.FULL, LineNumberMode.ENABLED)
        else:
            matching_subcontent = search_result['content']
        # Find most tolerable display level
        matching_module_content = None
        display_levels = [CodeDisplayLevel.FULL, CodeDisplayLevel.MODERATE, CodeDisplayLevel.SIGNATURE]
        final_display_level = None
        for display_level in display_levels:
            matching_module_content = matching_module.display(display_level, LineNumberMode.ENABLED)
            final_display_level = display_level
            if len(matching_module_content) < 32000:
                break
        prompt = f"""
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---
Here is the high-level overview of the {filename} file:
{matching_module_content}
---
Here a likely relevant content snippet. Use it for narrowing down the search:
{matching_subcontent}
---
{self.narrowing_instructions}
"""
        cache_key_parts = (instance_id, filename, search_result['elem_name'], search_result['parent_name'], search_result['elem_type'], search_result['split_idx'])
        cache_key_parts = [str(part) for part in cache_key_parts]
        cache_key = f"{self.subsystem}_narrowing_{'__'.join(cache_key_parts)}"
        print(f"CACHE KEY: {cache_key}")
        num_prompt_lines = len(prompt.split("\n"))
        num_module_lines = len(matching_module_content.split("\n"))
        print(f"Num Prompt Lines: {num_prompt_lines}")
        print(f"Num Module Lines: {num_module_lines}")
        if num_module_lines > 1000 or num_prompt_lines > 1000:
            print(cache_key)
            print(final_display_level)
            exit(0)
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=self.narrowing_system_msg, cache_key=cache_key)
        _reasons, codes, _attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="item", code_lang="json")
        contexts = []
        for result in codes.values():
            result = json.loads(result.strip())
            category = result['category']
            fn_name = result['fn_name']
            class_name = result['class_name']
            method_name = result['method_name']
            generic_lines = result['generic_lines']
            if fn_name is not None:
                display_level = CodeDisplayLevel.FULL if category == 'fix' else CodeDisplayLevel.MODERATE
                info = matching_module.display_function(fn_name, display_level, LineNumberMode.ENABLED)
            elif class_name is not None and method_name is not None:
                display_level = CodeDisplayLevel.FULL if category == 'fix' else CodeDisplayLevel.MODERATE
                info = matching_module.display_method(class_name, method_name, display_level, LineNumberMode.ENABLED)
            elif class_name is not None:
                display_level = CodeDisplayLevel.MODERATE if category == 'fix' else CodeDisplayLevel.SIGNATURE
                info = matching_module.display_class(class_name, display_level, LineNumberMode.ENABLED)
            elif generic_lines is not None:
                lo, hi = generic_lines
                lo = lo - 1 if lo > 0 else lo
                lines = matching_module.source_file.lines[lo:hi+1]
                info = matching_module.source_file.display_content(lines, lo, LineNumberMode.ENABLED)
            context = {
                'key': (category, filename, fn_name, class_name, method_name),
                'filename': filename,
                'category': category,
                'reasoning': result['reasoning'],
                'info': info,
                'search_result': search_result,
            }
            contexts.append(context)
        return contexts

    
    def make_final_selection(self, item: t.Dict[str, t.Any], code_search: CodeSearch, contexts: t.List[t.Dict[str, t.Any]]):
        instance_id = item["instance_id"]
        issue = item["problem_statement"]
        repo = item["repo"]
        relevant_contexts = []
        for i, context in enumerate(contexts):
            rank = i
            index = i
            category = context['category']
            filename = context['filename']
            reasoning = context['reasoning']
            info = context['info']
            brief_description = f"File: {filename}"
            search_result = context['search_result']
            elem_type = search_result['elem_type']
            if elem_type == "function":
                brief_description = f"""Function "{search_result['elem_name']}" in file {filename}"""
            elif elem_type == "method":
                brief_description = f"""Method "{search_result['parent_name']}.{search_result['elem_name']}" file {filename}"""
            relevant_contexts.append(f"""
---
Rank: {rank}
Index: {index}
Category: {category}
{brief_description}

Content:
{info}
---
            """.strip())
        relevant_contexts = "\n".join(relevant_contexts)
        prompt = f"""
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---
Here are the final selections:
{relevant_contexts}
---
{self.final_selection_instructions}
"""
        cache_key = f"{self.subsystem}_final_selection_{instance_id}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=self.final_selection_system_msg, cache_key=cache_key)
        _reasons, codes, _attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="final", code_lang="json")
        exit(0)
        assert len(codes) == 1
        code = codes["final"].strip()
        code = json.loads(code)
        return code["relevant"]

        