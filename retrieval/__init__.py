import tomllib
import os
from datasets import load_dataset
import pickle
from enum import Enum
from common.interfaces import FileDisplayLevel, RetrievedFile
import typing as t


class RetrieverType:
    GOLD = "gold"


class Retriever:
    """Generic retriever class."""
    def __init__(self, retriever_name, dataset_name: str, split="dev", num_shards=None, shard_id=None, load_cache=True):
        """Initialize the retriever."""
        # Load working directory from config.
        self.config = tomllib.load(open("configs/main.toml", "rb"))
        working_stage = self.config["working_stage"]
        os.makedirs(working_stage, exist_ok=True)
        # Load the dataset
        self.dataset_name = dataset_name
        self.dataset = load_dataset(dataset_name, split=split)
        self.shard_id = shard_id
        self.num_shards = num_shards
        self.split = split
        if shard_id is not None:
            print(f"Sharding dataset into {num_shards} shards and using shard {shard_id}")
            self.dataset = self.dataset.shard(num_shards, shard_id)
        # Check cache.
        self.retriever_name = retriever_name
        if shard_id is None:
            cache_file = f"{retriever_name}_retrieved_{dataset_name.replace('/', '__')}_{split}.pkl"
        else:
            cache_file = f"{retriever_name}_retrieved_{dataset_name.replace('/', '__')}_{split}_{num_shards}_{shard_id}.pkl"
        self.cache_file = f"{working_stage}/{cache_file}"
        self.cached_data = None
        if load_cache and os.path.exists(self.cache_file):
            print(f"Loading cache from {self.cache_file}")
            with open(self.cache_file, "rb") as f:
                self.cached_data = pickle.load(f)
        # Repo download dir.
        self.repo_download_dir = f"{working_stage}/downloaded_repos"
        assert len(self.repo_download_dir) > 5 # Just to be sure
        os.makedirs(self.repo_download_dir, exist_ok=True)


    def save_to_cache(self, cached_data):
        self.cached_data = cached_data
        with open(self.cache_file, "wb") as f:
            pickle.dump(cached_data, f)


    def format_for_context(self, instance_id: str, display_level: FileDisplayLevel) -> str:
        """Format the retrieved files for context."""
        raise NotImplementedError()
            

    def format_tests_for_context(self, instance_id: str) -> str:
        """Format the test cases for context."""
        raise NotImplementedError()

    def get_retrieved_files(self, instance_id: str) -> t.List[RetrievedFile]:
        """Get the retrieved files for the given instance id."""
        raise NotImplementedError()