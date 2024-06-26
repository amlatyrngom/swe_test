from retrieval import Retriever
import pickle
import os
from enum import Enum
from common import LLMType
import tomllib

class FixerType(Enum):
    DIRECT = "direct"


class Fixer:
    def __init__(self, fixer_name: str, retriever: Retriever, load_cache=True, verbose=False):
        self.retriever = retriever
        self.llm_type = LLMType.from_string(retriever.config["llm_type"])
        if retriever.shard_id is None:
            cache_file = f"{fixer_name}_fixes_{self.llm_type.value}_{retriever.dataset_name.replace('/', '__')}_{retriever.split}.pkl"
        else:
            cache_file = f"{fixer_name}_fixes_{self.llm_type.value}_{retriever.dataset_name.replace('/', '__')}_{retriever.split}_{retriever.num_shards}_{retriever.shard_id}.pkl"
        self.cache_file = f"{retriever.config['working_stage']}/{cache_file}"
        self.result_file = self.cache_file[:-3] + "jsonl"


        self.cached_data = None
        if load_cache and os.path.exists(self.cache_file):
            print(f"Loading cache from {self.cache_file}")
            with open(self.cache_file, "rb") as f:
                self.cached_data = pickle.load(f)
        injection_file = self.retriever.config["injections"]
        with open(injection_file, "rb") as f:
            injections = tomllib.load(f)
        self.injections = {
            k: v['content'] for k, v in injections.items() if v.get('enabled', True)
        }
        self.verbose = verbose

        
    def save_to_cache(self, cached_data):
        self.cached_data = cached_data
        with open(self.cache_file, "wb") as f:
            pickle.dump(cached_data, f)

    def format_for_context(self, instance_id: str) -> str:
        """Format the fixes for the given id."""
        raise NotImplementedError()

    def to_patch(self, fix):
        """Convert a fix to a patch."""
        raise NotImplementedError()
