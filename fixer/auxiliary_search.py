from common.handles import LANGUAGE_MODEL, TEXT_SEARCH
from .module import SourceCodeIndex, CodeDisplayLevel, LineNumberMode
import typing as t
import json


SYSTEM_MSG = """
Based on a github issue, and the likely bug, I want help finding relevant auxiliary code to use in addressing the issue.
Auxialiary code includes:
- Existing functions or methods that make the fix easier.
- Functions that I must use in the fix.
- Objects/Exceptions that I should use or return.
- Any other common sense code you think I should use.
""".strip()


SEARCH_FORMULATION_SYSTEM_MSG = f"""
{SYSTEM_MSG}

From the issue and the code, formulate search queries that will help me find the relevant code.
Search can be exact or approximate/semantic: both are useful.
You can search for files, functions, classes, methods by their actual names, or by their meaning or functionality for approximate search.
""".strip()

SEARCH_FORMULATION_INSTRUCTIONS = """
Formulate a list of search queries that are likely to return relevant auxiliary code.

There are several kinds of queries:
- Exact function search. The query should be {"fn_name": [function name]}.
- Exact method search. The query should be {"class_name": [class name], "method_name": [method name]}.
- Exact class search. The query should be {"class_name": [class name]}.
- Exact file search. The query should be {"filename": [filename], line_start: [line number], line_end: [line number]}
    - Set line_end to -1 if you want to search until the end of the file, but prefer fewer lines.
    - filenames are relative the repository root.
- Semantic search. The query should be {"semantic": [semantic description]}.
    - Very useful for utility or helper functions, or when the exact name is not known.
    - Should be like:
        - "Function that returns ..." or "Function that does ...".
        - "Class that represents ...".
        - One at a time: instead of "Function that does X or Y", search for "Function that does X" and "Function that does Y" as separate queries.
        - etc.

Make your searches as specific as possible. Avoid whole file searche when you know what you are looking for.
Likewise, prefer exact search over semantic search, unless looking for utility functions.

Format your output as follows:
<reason>
```md
# Your reasoning for the search queries.
```
</reason>

<queries>
```json
[
    {
        "reasoning": "Your reasoning for this query.",
        "query": {query dictionary},
    },
    ...
]
```
</queries>

When no queries are needed, simply return an empty list.
Be sure to respect the tags (reason, queries) and the JSON format in your response.
""".strip()


FILE_FILTER_SYSTEM_MSG = f"""
{SYSTEM_MSG}


Help find the files that are relevant to my search query.

In general, main source directory and files are relevant.
In general, test, configuration, example, documentation directories and files are not relevant unless the issue very specifically involves them. 
"""

FILE_FILTER_INSTRUCTIONS = """
Give me only the files that are likely to contain what my search query is looking for.

Here are some tips:
- When I am looking for a specific function, method, or class, only give me implementation files that likely contain them.
- In general, keep utility/helper files.

Format your output as follows:
<reason>
```md
# Your overall reasoning for the files.
```
</reason>

<files>
```json
[
    "file1",
    "file2",
    ...
]
```
</files>

When no files are needed, simply return an empty list.
Be sure to respect the tags (reason, files) and the JSON format in your response.
"""

RESULT_FILTER_SYSTEM_MSG = f"""
{SYSTEM_MSG}

Help me figure out of the result is most relevant to my search query.
"""

RESULT_FILTER_INSTRUCTIONS = """
Give me only the results that actually to contain what my search query is looking for.

I have given you the index of each item. Give me the index that best matches the search query.
Here are some tips:
- Prefer general functions to specific ones.
    * E.g., a function that solves problem for all input types is better than one that solves it for a specific type.
- Prefer public functions to private ones (starting with a '_'), unless the private function is clearly the better result.

Format your output as follows:
<reason>
```md
# Your overall reasoning.
```
</reason>

<result>
```json
{
    "index": [index],
}
</result>
"""

EXTRACTION_SYSTEM_MSG = f"""
{SYSTEM_MSG}

Help me extract the specific functionality that my search query is looking for.
"""

EXTRACTION_INSTRUCTIONS = """
Extract the specific functionality that my search query is looking for.
There are several kinds of extractions:
- Function: The extraction should be {"fn_name": [function name]}.
- Method: The extract should be {"class_name": [class name], "method_name": [method name]}.
- Whole Class: The query should be {"class_name": [class name]}.
- File Section: The query should be {"filename": [filename], line_start: [line number], line_end: [line number]}

Some tips:
- There may be multiple items to extract, but generally 0 or 1. Return an empty list when nothing is relevant or if you don't know.
- The file content may only contain signature and/comments. That should be enough to extract what I am looking for if present.
- Don't be confused by names that look similar, but describe different logic.
- Sometimes, an item will contain an import or a reference to what I am looking for. That is also useful.


Format your output as follows:
<reason>
```md
# Your overall reasoning for the extraction.
```
</reason>

<extractions>
```json
[
    {
        "reasoning": "Your reasoning for this extraction.",
        "extract": {extract dictionary},
    }
]
```
</extractions>
"""


FINAL_SELECTION_SYSTEM_MSG = f"""
{SYSTEM_MSG}

Help me select the auxiliary code that I should use in the fix.
Only filter out clearly irrelevant code.
Keep everything else that is likely to be useful, especially general utility functions, classes, or methods.
"""

FINAL_SELECTION_INSTRUCTIONS = """
Select the final auxiliary that I should use in the fix.
I have given you the index of each item. Give me all the indices that I should keep.
Keep everything that is likely to be useful, especially general utility functions, classes, or methods.


There may be multiple items to keep. Return an empty list when nothing is relevant or if you don't know.

Format your output as follows:
<reason>
```md
# Your overall reasoning.
```
</reason>

<selection>
```json
[
    {
        "reasoning": "Your reasoning for this selection.",
        "index": index1,
    },
    ...
]
```
</selection>
"""


class AuxiliarySearch:
    def __init__(self):
        pass

    def perform_aux_search(self, code_index: SourceCodeIndex, additional_context: str=""):
        search_queries = self.formulate_search_queries(code_index, additional_context)
        print(search_queries)
        best_search_results = []
        for i, (reasoning, query) in enumerate(search_queries):
            if self._is_query_exact(query):
                results = self.try_exact_search(code_index, query, reasoning, i)
            elif self._is_query_semantic(query):
                results = self.try_text_search(code_index, query['semantic'], reasoning, i, approximate=True)
            if len(results) == 0:
                continue
            if len(results) == 1:
                best_index = 0
            else:
                best_index = self.quality_search_results(code_index, query, reasoning, i, results)
                # if 'semantic' in query and 'infer' in query['semantic']:
                #     exit(0)
                best_index = best_index["index"]
                if isinstance(best_index, list):
                    best_index = best_index[0]
            result = results[best_index]
            print(f"Query {query}. Result file: {result[0]}. Result code:\n{result[1]}")
            best_search_results.append(result)
        aux = self.final_decision(code_index, best_search_results, additional_context)
        final_aux_context = []
        for r in aux:
            filename, code = best_search_results[r["index"]]
            context = f"""
~~~~~
Potentially helpful auxialliary information:
From Filename: {filename}
Auxiliary Sub Content:
{code}
~~~~~
""".strip()            
            final_aux_context.append(context)
        if len(final_aux_context) == 0:
            return ""
        final_aux_context = "\n".join(final_aux_context)
        final_aux_context = f"""
~~~~~~~~~~~~~~~
Here are auxiliary code snippets that you may be able to use in the fix:
{final_aux_context}
~~~~~~~~~~~~~~~
""".strip()
        return final_aux_context

    def formulate_search_queries(self, code_index: SourceCodeIndex, additional_context: t.Optional[str] = None):
        instance_id = code_index.dataset_item["instance_id"]
        issue = code_index.dataset_item["problem_statement"]
        repo = code_index.dataset_item["repo"]
        prompt = f"""
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---
{additional_context}
---
Your task: {SEARCH_FORMULATION_INSTRUCTIONS}
"""
        cache_key = f"auxiliary_search_{instance_id}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=SEARCH_FORMULATION_SYSTEM_MSG, cache_key=cache_key)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="queries", code_lang="json")
        code = codes["queries"].strip()
        code = json.loads(code)
        search_queries = []
        for query in code:
            reasoning = query["reasoning"]
            query = query["query"]
            search_queries.append((reasoning, query))
        return search_queries
    

    def _is_query_fn(self, query: t.Dict[str, str]):
        return "fn_name" in query
    
    def _is_query_method(self, query: t.Dict[str, str]):
        return "class_name" in query and "method_name" in query
    
    def _is_query_class(self, query: t.Dict[str, str]):
        return "class_name" in query and "method_name" not in query
    
    def _is_query_file(self, query: t.Dict[str, str]):
        return "filename" in query

    def _is_query_semantic(self, query: t.Dict[str, str]):
        return "semantic" in query
    
    def _is_query_exact(self, query: t.Dict[str, str]):
        return not self._is_query_semantic(query)

    def _find_exact_fn(self, code_index: SourceCodeIndex, fn_name: str):
        results = []
        for filename, module in code_index.modules.items():
            if fn_name in module.functions:
                fn = module.display_function(fn_name, level=CodeDisplayLevel.MODERATE, line_mode=LineNumberMode.ENABLED)
                results.append((filename, fn))
        return results
    
    def _find_exact_method(self, code_index: SourceCodeIndex, class_name: str, method_name: str):
        results = []
        for filename, module in code_index.modules.items():
            if class_name in module.classes and method_name in module.classes[class_name].methods:
                method = module.display_method(class_name, method_name, level=CodeDisplayLevel.MODERATE, line_mode=LineNumberMode.ENABLED)
                results.append((filename, method))
        return results
    
    def _find_exact_class(self, code_index: SourceCodeIndex, class_name: str):
        results = []
        for filename, module in code_index.modules.items():
            if class_name in module.classes:
                klass = module.display_class(class_name, level=CodeDisplayLevel.MODERATE, line_mode=LineNumberMode.ENABLED)
                if len(klass) > 5000:
                    klass = module.display_class(class_name, level=CodeDisplayLevel.SIGNATURE, line_mode=LineNumberMode.ENABLED)
                results.append((filename, klass))
        return results
    
    def _find_exact_file(self, code_index: SourceCodeIndex, filename: str, line_start: int, line_end: int):
        if filename not in code_index.modules:
            return []
        module = code_index.modules[filename]
        lines = module.source_file.lines
        line_start = max(0, line_start - 10)
        if line_end == -1:
            line_end = len(lines)
        line_end = min(len(lines), line_end + 10)
        content = module.source_file.display_content(lines[line_start:line_end], line_start, line_number_mode=LineNumberMode.ENABLED)
        if len(content) > 20000:
            content = module.display(level=CodeDisplayLevel.SIGNATURE, line_mode=LineNumberMode.ENABLED)
        return [(filename, content)]

    def _extract_in_file(self, code_index: SourceCodeIndex, filename: str, query: t.Dict[str, str]):
        if filename not in code_index.modules:
            return None
        module = code_index.modules[filename]
        if self._is_query_fn(query):
            fn_name = query["fn_name"]
            if fn_name in module.functions:
                return module.display_function(fn_name, level=CodeDisplayLevel.MODERATE, line_mode=LineNumberMode.ENABLED)
        elif self._is_query_method(query):
            class_name = query["class_name"]
            method_name = query["method_name"]
            if class_name in module.classes and method_name in module.classes[class_name].methods:
                return module.display_method(class_name, method_name, level=CodeDisplayLevel.MODERATE, line_mode=LineNumberMode.ENABLED)
        elif self._is_query_class(query):
            class_name = query["class_name"]
            if class_name in module.classes:
                klass = module.display_class(class_name, level=CodeDisplayLevel.MODERATE, line_mode=LineNumberMode.ENABLED)
                if len(klass) > 10000:
                    klass = module.display_class(class_name, level=CodeDisplayLevel.SIGNATURE, line_mode=LineNumberMode.ENABLED)
                return klass
        elif self._is_query_file(query):
            result = self._find_exact_file(code_index, filename, query["line_start"], query["line_end"])
            if len(result) > 0:
                return result[0][1]
            return None
        else:
            raise ValueError(f"Invalid extraction query type: {query}")

    def try_exact_search(self, code_index: SourceCodeIndex, query: t.Dict[str, str], reasoning: str, query_idx: int):
        results = []
        alternative = None
        if self._is_query_fn(query):
            fn_name = query["fn_name"]
            results = self._find_exact_fn(code_index, fn_name)
            if len(results) == 0:
                alternative = fn_name
        elif self._is_query_method(query):
            class_name = query["class_name"]
            method_name = query["method_name"]
            results = self._find_exact_method(code_index, class_name, method_name)
            if len(results) == 0:
                alternative = f"{class_name} {method_name}"
        elif self._is_query_class(query):
            class_name = query["class_name"]
            results = self._find_exact_class(code_index, class_name)
            if len(results) == 0:
                alternative = class_name
        elif self._is_query_file(query):
            filename = query["filename"]
            line_start = query["line_start"]
            line_end = query["line_end"]
            results = self._find_exact_file(code_index, filename, line_start, line_end)
            if len(results) == 0:
                alternative = filename
        if len(results) == 0:
            return self.try_text_search(code_index, alternative, reasoning, query_idx, approximate=False)
        print(f"Relevant files: {results}")
        filenames = [filename for filename, _ in results]
        filenames = self.file_filter(code_index, query, reasoning, query_idx, filenames)
        print(f"Relevant files: {filenames}")
        filenames = set(filenames)
        results = [(filename, code) for filename, code in results if filename in filenames]
        if len(results) == 0:
            return self.try_text_search(code_index, alternative, reasoning, query_idx, approximate=False)
        return results
        

    def file_filter(self, code_index: SourceCodeIndex, query: str, reasoning: str, query_idx: int, filenames: t.List[str]):
        instance_id = code_index.dataset_item["instance_id"]
        issue = code_index.dataset_item["problem_statement"]
        repo = code_index.dataset_item["repo"]
        filenames = "\n".join(filenames)
        prompt = f"""
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---

Here is the search query:
{reasoning}
Query: {query}
---
Here a are the files I am considering for the search:
{filenames}
---
Your task: {FILE_FILTER_INSTRUCTIONS}
"""
        cache_key = f"auxiliary_search_file_filter_{instance_id}_{query_idx}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=FILE_FILTER_SYSTEM_MSG, cache_key=cache_key)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="files", code_lang="json")
        files = codes["files"].strip()
        files = json.loads(files)
        return files
    

    def quality_search_results(self, code_index: SourceCodeIndex, query: str, reasoning: str, query_idx: int, results: t.List[t.Tuple[str, str]]):
        instance_id = code_index.dataset_item["instance_id"]
        issue = code_index.dataset_item["problem_statement"]
        repo = code_index.dataset_item["repo"]
        results_context = []
        for result_index, result in enumerate(results):
            filename, code = result
            result_context = f"""
---
Result Index: {result_index}
Filename: {filename}
Search Result:
{code}
---
""".strip()
            results_context.append(result_context)
        results_context = "\n".join(results_context)
        prompt = f"""
Repo: {repo}
---
Here a are the search results:
{results_context}
---
Here is my search query:
{reasoning}
Query: {query}
---
Your task: {RESULT_FILTER_INSTRUCTIONS}
"""
        cache_key = f"auxiliary_search_result_filter_{instance_id}_{query_idx}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=RESULT_FILTER_SYSTEM_MSG, cache_key=cache_key)
        # if 'semantic' in query and 'infer' in query['semantic']:
        #     print(response)
        #     exit(0)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="result", code_lang="json")
        results = codes["result"].strip()
        results = json.loads(results)
        return results
    
    def extract_functionality(self, code_index: SourceCodeIndex, query: str, reasoning: str, query_idx: int, result: t.Dict[str, t.Any], result_idx: int):
        instance_id = code_index.dataset_item["instance_id"]
        issue = code_index.dataset_item["problem_statement"]
        repo = code_index.dataset_item["repo"]
        filename, content = result['filename'], result['content']
        matching_module = code_index.modules[filename]
        if result['elem_type'] == "module" and result["split_idx"] != 0:
            module_context = matching_module.display(level=CodeDisplayLevel.SIGNATURE, line_mode=LineNumberMode.ENABLED)
            module_context = f"""Here is the overall module signature:\m{module_context}"""
        else:
            module_context = ""
        prompt = f"""
Repo: {repo}
---
Filename: {filename}
{module_context}

Search Result. This is possibly where the functionality is, if present:
{content}
---
Here is my search query:
{reasoning}
Query: {query}
---
Your task: {EXTRACTION_INSTRUCTIONS}
"""
        cache_key = f"auxiliary_search_extraction_{instance_id}_{query_idx}_{result_idx}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=EXTRACTION_SYSTEM_MSG, cache_key=cache_key)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="extractions", code_lang="json")
        extractions = codes["extractions"].strip()
        extractions = json.loads(extractions)
        extractions = [self._extract_in_file(code_index, filename, extraction['extract']) for extraction in extractions]
        return [extraction for extraction in extractions if extraction is not None]
    
    def try_text_search(self, code_index: SourceCodeIndex, query: str, reasoning: str, query_idx: int, approximate: bool = True):
        if any(["Function that" in q for q in (query, reasoning)]):
            elem_type = "function"
        elif any(["Class that" in q for q in (query, reasoning)]):
            elem_type = "class"
        else:
            elem_type = "code"
        elem_type = "code"
        instance_id = code_index.dataset_item["instance_id"]
        if approximate:
            cache_key = f"auxiliary_search_query_{instance_id}_{query_idx}"
            results = TEXT_SEARCH.approximate_search(instance_id, query=query, num_results=25, elem_type=elem_type, cache_key=cache_key, dedup_by_file=True)
        else:
            results = TEXT_SEARCH.exact_search(instance_id, query=query, num_results=10, elem_type="code")
        filenames = [result["filename"] for result in results]
        print(query)
        print(f"Pre-Relevant files: {filenames}")
        filenames = self.file_filter(code_index, query, reasoning, query_idx, filenames)
        print(f"Relevant files: {filenames}")
        filenames = set(filenames)
        results = [result for result in results if result["filename"] in filenames]
        extracted_results = []
        for i, result in enumerate(results):
            extractions = self.extract_functionality(code_index, query, reasoning, query_idx, result, i)
            print(f"Extractions: {extractions}")
            extracted_results.extend([(result['filename'], extraction) for extraction in extractions])
        print(f"Extracted Results: {extracted_results}")
        return extracted_results
    
    def final_decision(self, code_index: SourceCodeIndex, results: t.List[t.Tuple[str, str]], additional_context: t.Optional[str] = None):
        instance_id = code_index.dataset_item["instance_id"]
        issue = code_index.dataset_item["problem_statement"]
        repo = code_index.dataset_item["repo"]
        results_context = []
        for result_index, result in enumerate(results):
            filename, code = result
            result_context = f"""
---
Result Index: {result_index}
Filename: {filename}
Potential Auxiliary Code:
{code}
---
""".strip()
            results_context.append(result_context)
        results_context = "\n".join(results_context)
        prompt = f"""
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---
Here are the potential auxiliary codes:
{results_context}
---
Your task: {FINAL_SELECTION_INSTRUCTIONS}
"""
        cache_key = f"auxiliary_search_final_selection_{instance_id}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=FINAL_SELECTION_SYSTEM_MSG, cache_key=cache_key)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="selection", code_lang="json")
        selection = codes["selection"].strip()
        selection = json.loads(selection)
        return selection


AUX_SEARCH = AuxiliarySearch()