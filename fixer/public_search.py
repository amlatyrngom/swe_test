from common.handles import LANGUAGE_MODEL, TEXT_SEARCH, CACHE
import typing as t
import json
from googlesearch import search as google_search
from bs4 import BeautifulSoup
import requests


FORMULATE_SEARCH_SYSTEM_MSG = f"""
Based on a github issue, you will help me search the internet for auxiliary information that can help me solve the issue.
Auxiliary information can include:
- External public library: Code/Documentation snippets for an external public library that can help solve the issue.
- Complex Algorithm: Descriptions of a complex algorithms if the issue requires it.
- Standard Representations/Formats: General information for me to understand the standard representations or formats used in the issue.
- Advanced Concepts: Advanced concepts that can help me understand the issue better.

Help me formulate a set of search queries that can help me find the information I need to solve the issue.
Don't search for something simply because it is mentioned in the issue, only search for advanced information that can help me solve the issue.
NEVER search anything about the repository itself. It should be about external libraries, algorithms, formats, etc.
In particular, your search queries should never mention the repository itself.
"""

FORMULATE_SEARCH_INSTRUCTIONS = """
Formulate a list of search queries that are likely to return relevant auxiliary information.
The search query will be a string I will feed into Google to find the information I need.

There are several kinds of queries:
- External public library: set `query_type` to "external_library".
- Complex Algorithm: set `query_type` to "complex_algorithm".
- Standard Format/Representation: set `query_type` to "standard_format".
- Advanced Conceptual Information: set `query_type` to "advanced_concept".




For example, if you are want to know how to make a POST request using the `requests` library, you can formulate a search query like:
    - {"query_type": "external_library", "query": "Make a POST request using requests library Python."}
Do not search for generic Python functionality like "how to open a file in Python", "how to sort a list in Python", etc.


You can provide multiple search queries. If no internet search is needed, give me an empty list.


Format your response as follows:

<reason>
```md
# Your overall reasoning.
```
</reason>


<queries>
```json
[
    {
        "reason": "Your reasoning for this particular query.",
        "query_type": "The type of query",
        "query": "The search query"
    },
    ...
]
```
</queries>


Be sure to respect the tags (<reason> and <queries>) and the JSON format for the queries.
NEVER search anything about the repository itself. It should be about external libraries, algorithms, formats, etc.
In particular, your search queries should never mention the repository itself.
"""


# NOTE: No need to include the overall system message for this particular prompt.
BEST_RESULT_SYSTEM_MSG = f"""
Help me select the best results for my search query.
Here are some guidelines:
- Prefer official/reputable, up-to-date documentation.
- Avoid github issues/PRs.
- Except, perhaps, for stackoverflow, avoid forums.
- Comprehensive to partial information.
"""


BEST_RESULT_INSTRUCTIONS = """
Give me the index of the best search results that can help me solve the issue.
I have given both the description of the search result, and its index.
Select at most two results.

Format your response as follows:

<reason>
```md
# Your overall reasoning.
```
</reason>

<result>
```json
{
    "indices": [at most two indices for the best search results]
}
```
</result>

Be sure to respect the tags (<reason> and <result>) and the JSON format for the result.
"""


AGGREGATE_SYSTEM_MSG = f"""
Help aggregate information from the internet to answer my search query.
Here are some guidelines:
- When a table provides general information that answers the query, keep the whole table. You can summarize individual columns, but keep every row.
- Keep anything else you think is relevant to the query.
- Prioritize official documentation, reputable sources, and up-to-date information.
- Remove irrelevant information that mentions things unrelated to the search query.
"""

AGGREGATE_INSTRUCTIONS = """
Concisely aggregate the information from the search results to answer my search query.
Be sure to keep important information.

Format your response as follows:
<reason>
```md
# Your overall reasoning for the information you've kept.
```
</reason>

<aggregation>
```md
# The aggregated information from the search results.
```
</aggregation>

Be sure to respect the tags (<reason> and <aggregation>) and the markdown format for the aggregation.
"""



class PublicSearch:
    def __init__(self):
        pass

    def perform_public_search(self, item, additional_context: str = ""):
        search_queries = self.formulate_search_queries(item, additional_context)
        print(f"Search queries: {json.dumps(search_queries, indent=2)}")
        exit(0)
        aggregated_results = []
        for query_idx, (reasoning, query) in enumerate(search_queries):
            responses = self.internet_search(item, query, query_idx)
            if responses is None:
                print(f"No search results for query: {query}")
                continue
            for response in responses:
                print(f"URL: {response['url']}. Title: {response['title']}. Description:\n{response['description']}")
            if len(responses) > 2:
                responses = self.best_result(item, query, query_idx, responses)
            aggregated = self.aggregate(item, query, query_idx, responses)
            if self.is_self_referential(item, aggregated):
                # This may be overly conservative, but it's better to be safe.
                continue
            aggregated_results.append((query, aggregated))
        for query, aggregated in aggregated_results:
            print(f"Query: {query}. Aggregated:\n{aggregated}")
        exit(0)
        return aggregated_results


    def is_self_referential(self, item, s):
        repo = item['repo']
        repo = repo.split("/")[-1].lower()
        s = s.lower()
        return repo in s

    def formulate_search_queries(self, item, additional_context: str = ""):
        instance_id = item["instance_id"]
        repo = item["repo"]
        issue = item["problem_statement"]
        prompt = f"""
Repo: {repo}
---
Repo: {repo}
---
Start of Issue:
{issue}
End of Issue
---
{additional_context}
---
Your task: {FORMULATE_SEARCH_INSTRUCTIONS}
"""
        cache_key = f"public_search_formulate_{instance_id}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=FORMULATE_SEARCH_SYSTEM_MSG, cache_key=cache_key)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="queries", code_lang="json")
        code = codes["queries"].strip()
        code = json.loads(code)
        search_queries = []
        for query in code:
            reasoning = query["reason"]
            query = query["query"]
            search_queries.append((reasoning, query))
        return search_queries

    def aggregate(self, item, search_query, query_idx, search_results):
        if isinstance(search_results, str):
            search_contexts = search_results
        else:
            search_contexts = []
            for search_result in search_results:
                page_content = self._retrieve_page_content(item, query_idx, search_result["url"])
                page_content = page_content[:45000]
                search_context = f"""
---
URL: {search_result['url']}
Title: {search_result['title']}
Description:
{search_result['description']}
Extracted Page Content:

{page_content}
---
""".strip()
                search_contexts.append(search_context)
            search_contexts = "\n".join(search_contexts)
        prompt = f"""
Here is my search query:
{search_query}
---
Here are the search results:
{search_contexts}
---
Your task: {AGGREGATE_INSTRUCTIONS}
"""
        cache_key = f"public_search_aggregate_{item['instance_id']}_{query_idx}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=AGGREGATE_SYSTEM_MSG, cache_key=cache_key)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="aggregation", code_lang="md")
        code = codes["aggregation"].strip()
        return code

        

    def _retrieve_page_content(self, item, query_idx, url):
        cache_key = f"internet_retrieve_{item['instance_id']}_{query_idx}"
        cached_response = CACHE.get_prompt(cache_key, url)
        if cached_response is not None:
            return cached_response
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        body = soup.find("body")
        # Keep all except script and style tags
        for script in body(["script", "style", "head", "nav", "footer"]):
            script.decompose()
        text = body.get_text()
        CACHE.set_prompt(cache_key, url, text)
        return text


    def internet_search(self, item, search_query, query_idx):
        instance_id = item["instance_id"]
        cache_key = f"internet_search_{instance_id}_{query_idx}"
        cached_responses = CACHE.get_prompt(cache_key, search_query)
        if cached_responses is not None:
            return json.loads(cached_responses)
        results = google_search(search_query, num_results=5, timeout=20, sleep_interval=5, advanced=True)
        results = list(results)
        if len(results) == 0:
            return None
        search_results = [
            {
                    "url": result.url,
                    "title": result.title,
                    "description": result.description,
            }
            for result in results
        ]
        search_results = [
            result for result in search_results
            if not self.is_self_referential(item, f"{result['title']} {result['description']} {result['url']}")
            and not "/github.com" in result["url"]
        ]
        CACHE.set_prompt(cache_key, search_query, json.dumps(search_results))
        return search_results
    
    def best_result(self, item, search_query, query_idx, search_results):
        search_contexts = []
        for i, search_result in enumerate(search_results):
            search_context = f"""
---
Index: {i}
URL: {search_result['url']}
Title: {search_result['title']}
Description:
{search_result['description']}
---
""".strip()
            search_contexts.append(search_context)
        search_contexts = "\n".join(search_contexts)

        prompt = f"""
---
Here is my search query:
{search_query}
---
Here are the search results:
{search_contexts}
---
Your task: {BEST_RESULT_INSTRUCTIONS}
"""
        cache_key = f"public_search_best_{item['instance_id']}_{query_idx}"
        response = LANGUAGE_MODEL.invoke(prompt, system_msg=BEST_RESULT_SYSTEM_MSG, cache_key=cache_key)
        reasons, codes, attrs = LANGUAGE_MODEL.parse_standard_response(response, code_tag="result", code_lang="json")
        code = codes["result"].strip()
        code = json.loads(code)
        best_result = code["indices"]
        if isinstance(best_result, int):
            best_result = [best_result]
        return [search_results[i] for i in best_result]
        
    

PUBLIC_SEARCH = PublicSearch()

