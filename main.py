import argparse
from retrieval.gold import GoldenRetriever
from fixer.direct import DirectFixer, PromptingStrategy
from common import LLMType, call_llm
from common.interfaces import RetrievedFile, FileDisplayLevel
import datasets
import tomllib
import os
import dotenv
import openai
import boto3
from enum import Enum



def get_item_by_id(dataset: datasets.Dataset, item_id: str):
    for item in dataset:
        if item["instance_id"] == item_id:
            return item
    raise ValueError(f"Item with id {item_id} not found in dataset.")    

def get_simple_items(retriever: GoldenRetriever, llm_type: LLMType, max_num_edits=1):
    stats = retriever.collect_stats()
    items = {}
    working_stage = retriever.config["working_stage"]
    # Delete all files of the form essai-*.prompt
    for file in os.listdir(retriever.config["working_stage"]):
        if file.startswith("essai-prompt-") and file.endswith(".prompt"):
            os.remove(f"{working_stage}/{file}")
    for item in retriever.dataset:
        num_files = stats["num_files"][item["instance_id"]]
        num_edits = stats["num_edits"][item["instance_id"]]
        print(f"Num files: {num_files}, Num edits: {num_edits}")
        if num_files > 1 or num_edits > max_num_edits:
            continue
        retrieved = retriever.retrieved[item["instance_id"]]
        prompt = make_basic_prompt(retriever, item, retrieved)
        prompt_file = f"{working_stage}/essai-prompt-{item['instance_id']}.prompt"
        with open(prompt_file, "w") as f:
            f.write(prompt)
        items[item["instance_id"]] = (item, retrieved)
        resp = run_and_parse(prompt, llm_type)
        print(resp)
        exit(0)
    return items

def make_basic_prompt(retriever: GoldenRetriever, item, retrieved):
    repo = item["repo"]
    issue = item["problem_statement"]
    retrieved_context = retrieved[0].format_for_prompt(FileDisplayLevel.FILE_AND_LINES)
    output_instructions = retriever.config["output_instructions"]
    instructions = f"""
---
Repository: {repo}
---
Here is the issue:
Start of issue:
{issue}
End of issue.
---
{retrieved_context}
---
Your task: Fix the github issue by modifying the code in the files provided. I have given the exact lines that may need to be changed. DO NOT try to change any other lines.

{output_instructions}
"""
    return instructions


def parse_block(output: str, tag: str):
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
    return output[start_block:end_block], attrs


def run_and_parse(prompt: str, llm_type: LLMType):
    # Call LLM
    try:
        response = call_llm(prompt, llm_type)
        print(f"LLM Response:\n{response}")
    except Exception as e:
        print(e)
        exit(0)
    overall_explanation = parse_block(response, "mdblock")
    explanations = []
    codeblocks = []
    attrs = []
    i = 1
    while True:
        try:
            explanation, _ = parse_block(response, f"mdblock{i}")
            codeblock, block_attrs = parse_block(response, f"codeblock{i}")
            print(explanation)
            print(codeblock)
            print(block_attrs)
            explanations.append(explanation)
            codeblocks.append(codeblock)
            attrs.append(block_attrs)
            i += 1
        except:
            break
    return overall_explanation, explanations, codeblocks, attrs


def main(dataset, split, num_shards, shard_id, llm, force_retrieve, force_fix):
    llm_type = LLMType.from_string(llm)
    use_retriever_cache = not force_retrieve
    use_fixer_cache = not force_fix
    retriever = GoldenRetriever(dataset_name=dataset, split=split, num_shards=num_shards, shard_id=shard_id, load_cache=use_retriever_cache)
    fixer = DirectFixer(retriever=retriever, verbose=True, prompting_strategy=PromptingStrategy.ONE_SHOT_CODE_ONLY, load_cache=use_fixer_cache)
    fixer.serialize_all()
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="princeton-nlp/SWE-bench_Lite")
    parser.add_argument("--split", type=str, default="dev")
    parser.add_argument("--num_shards", type=int, default=None)
    parser.add_argument("--shard_id", type=int, default=None)
    parser.add_argument("--llm", type=str, default="claude3")
    parser.add_argument("--force_retrieve", action="store_true", default=False)
    parser.add_argument("--force_fix", action="store_true", default=False)
    args = parser.parse_args()
    main(**vars(args))
    exit(0)

