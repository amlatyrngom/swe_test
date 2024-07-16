import argparse
# from retrieval.gold import GoldenRetriever
# from fixer.direct import DirectFixer, PromptingStrategy
# from common import LLMType, call_llm
# from common.interfaces import RetrievedFile, FileDisplayLevel
from fixer.module import make_code_index
from common.handles import TEXT_SEARCH
import datasets
import tomllib
import os
import json
from collections import OrderedDict



def get_item_by_id(dataset: datasets.Dataset, item_id: str):
    for item in dataset:
        if item["instance_id"] == item_id:
            return item
    raise ValueError(f"Item with id {item_id} not found in dataset.")    


def make_dataset_index(force: bool = False):
    """Build the code search index for a dataset."""
    import datasets
    import threading
    from itertools import chain
    config = tomllib.load(open("configs/main.toml", "rb"))
    dataset_name = config["dataset"]
    split = config["split"]
    check_cache = not force
    dataset = datasets.load_dataset(dataset_name, split=split)
    parallelism = 8
    threads = []
    items = list(dataset)
    def make_chunks(items):
        by_repo = {}
        for item in items:
            repo = item["repo"]
            if repo not in by_repo:
                by_repo[repo] = []
            by_repo[repo].append(item)
        chunk_size = len(by_repo) // parallelism
        n = max(1, chunk_size)
        by_repo = list(by_repo.values())
        return [by_repo[i:i+n] for i in range(0, len(by_repo), n)]
    chunks = make_chunks(items)
    chunks = [chunk for chunk in chunks if len(chunk) > 0]
    def _build_dataset_index(items, check_cache, thread_idx):
        items = list(chain(*items))
        for item in items:
            make_code_index(item, check_cache=check_cache)
    for i, chunk in enumerate(chunks):
        thread = threading.Thread(target=_build_dataset_index, args=(chunk, check_cache, i))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()


def main_try_code_search(instance_id: str, force: bool = False, query = None, exact = False):
    """Try to use a code search object."""
    config = tomllib.load(open("configs/main.toml", "rb"))
    dataset_name = config["dataset"]
    split = config["split"]
    dataset = datasets.load_dataset(dataset_name, split=split)
    item = get_item_by_id(dataset, instance_id)
    check_cache = not force
    code_index = make_code_index(item, check_cache=check_cache)
    dirs = ["astroid"]
    print(f"Relevant Dirs: {dirs}")
    # print(f"Relevant Dirs: {dirs}")
    if query is None:
        query = item["problem_statement"]
    if exact:
        results = TEXT_SEARCH.exact_search(instance_id, query=query, num_results=3, elem_type="code", in_dirs=dirs)
    else:
        results = TEXT_SEARCH.approximate_search(instance_id, query=query, num_results=3, elem_type="code", in_dirs=dirs, cache_key=f"try-code-search-{instance_id}")
    show_items = ['filename', 'parent_name', 'elem_name', 'elem_type', 'split_idx', 'distance']
    print(f"Results: {[{k: v for k, v in result.items() if k in show_items} for result in results]}")
    # candidates = OrderedDict([(result['filename'], ()) for result in results])
    # candidate_ranks = [(filename, i) for i, filename in enumerate(candidates.keys())]
    # good_candidates = dir_selection.refine_files(item, code_search, candidate_ranks)
    # print(f"Results: {[{k: v for k, v in result.items() if k in show_items} for result in results]}")
    # refined_results = [result for result in results if result['filename'] in good_candidates]
    # print(f"Refined Results: {[{k: v for k, v in result.items() if k in show_items} for result in refined_results]}")
    # full_contexts = OrderedDict()
    # for search_result in refined_results:
    #     contexts = dir_selection.narrow_down_result(item, code_search, search_result)
    #     for context in contexts:
    #         full_contexts[context['key']] = context
    # full_contexts = list(full_contexts.values())
    # dir_selection.make_final_selection(item, code_search, full_contexts)    

    # print(json.dumps(results, indent=2))
    print(TEXT_SEARCH.db_idx(instance_id))

def aux_search(instance_id: str, force: bool = False):
    from fixer.auxiliary_search import AuxiliarySearch
    config = tomllib.load(open("configs/main.toml", "rb"))
    dataset_name = config["dataset"]
    split = config["split"]
    dataset = datasets.load_dataset(dataset_name, split=split)
    item = get_item_by_id(dataset, instance_id)
    check_cache = not force
    code_index = make_code_index(item, check_cache=check_cache)
    aux_search = AuxiliarySearch()
    additional_context = ""# item["hints_text"].strip()
    if len(additional_context) > 0:
        additional_context = f"""Here is additional context from a conversation that may be helpful:\n{additional_context}"""
    aux_search.perform_aux_search(item, code_index, additional_context=additional_context)
    print(item['patch'])


def public_search(instance_id: str):
    from fixer.public_search import PublicSearch
    config = tomllib.load(open("configs/main.toml", "rb"))
    dataset_name = config["dataset"]
    split = config["split"]
    dataset = datasets.load_dataset(dataset_name, split=split)
    item = get_item_by_id(dataset, instance_id)
    public_search = PublicSearch()
    additional_context = ""# item["hints_text"].strip()
    if len(additional_context) > 0:
        additional_context = f"""Here is additional context from a conversation that may be helpful:\n{additional_context}"""
    public_search.perform_public_search(item, additional_context=additional_context)


def basic_fix(instance_id: str, force: bool = False):
    from fixer.direct import DirectFixer
    check_cache = not force
    fixer = DirectFixer(specific_instance_ids=[instance_id], check_cache=check_cache)
    fixer.make_fixes()


# def main(dataset, split, num_shards, shard_id, llm, force_retrieve, force_fix):
    # llm_type = LLMType.from_string(llm)
    # use_retriever_cache = not force_retrieve
    # use_fixer_cache = not force_fix
    # retriever = GoldenRetriever(dataset_name=dataset, split=split, num_shards=num_shards, shard_id=shard_id, load_cache=use_retriever_cache)
    # fixer = DirectFixer(retriever=retriever, verbose=True, prompting_strategy=PromptingStrategy.ONE_SHOT_WITH_TESTS, load_cache=use_fixer_cache)
    # fixer.serialize_all()
    # simple_items = get_simple_items(retriever=retriever, llm_type=llm_type, max_num_edits=1)
    # sample_id = "pvlib__pvlib-python-1854"
    # retrieved = retriever.retrieved[sample_id]
    # gold_patch = retriever.gold_patches[sample_id]
    # issue = get_item_by_id(retriever.dataset, sample_id)["problem_statement"]
    # print(retrieved[0].format_for_prompt(FileDisplayLevel.FILE_AND_LINES))
    # print(str(gold_patch))
    # print(issue)
    pass

if __name__ == "__main__":
    # Some nonsense
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(help="Sub-commands")
    # Build indices
    build_indices_parser = subparsers.add_parser("build-code-index")
    build_indices_parser.add_argument("--force", action="store_true", default=False)
    build_indices_parser.set_defaults(func=make_dataset_index)
    # Try code search
    try_code_search_parser = subparsers.add_parser("try-code-search")
    try_code_search_parser.add_argument("instance_id", type=str, default="sqlfluff__sqlfluff-1625")
    try_code_search_parser.add_argument("--force", action="store_true", default=False)
    try_code_search_parser.add_argument("--query", type=str, default=None)
    try_code_search_parser.add_argument("--exact", action="store_true", default=False)
    try_code_search_parser.set_defaults(func=main_try_code_search)
    # Auxilliary search
    aux_search_parser = subparsers.add_parser("aux-search")
    aux_search_parser.add_argument("instance_id", type=str, default="sqlfluff__sqlfluff-1625")
    aux_search_parser.add_argument("--force", action="store_true", default=False)
    aux_search_parser.set_defaults(func=aux_search)
    # Public search
    public_search_parser = subparsers.add_parser("public-search")
    public_search_parser.add_argument("instance_id", type=str, default="sqlfluff__sqlfluff-1625")
    public_search_parser.set_defaults(func=public_search)
    # Basic fix
    basic_fix_parser = subparsers.add_parser("basic-fix")
    basic_fix_parser.add_argument("instance_id", type=str, default="sqlfluff__sqlfluff-1625")
    basic_fix_parser.add_argument("--force", action="store_true", default=False)
    basic_fix_parser.set_defaults(func=basic_fix)
    # Execute
    args = parser.parse_args()
    func = args.func
    del args.func
    func(**vars(args))
    # Some nonsense

