import unidiff
import git
import dotenv
import os
from common import download_repo
from common.interfaces import RetrievedFile, FileDisplayLevel
import typing as t
from . import Retriever

dotenv.load_dotenv()
github_token = os.getenv("GITHUB_TOKEN")




    


class GoldenRetriever(Retriever):
    """
    Retrieves files touched by the gold patch.
    This should be the baseline. It is hard, but not impossible, to beat this retriever.
    For example it does not recursively retrieve files that are imported by the files in the gold patch.
    """
    def __init__(self, dataset_name: str, split="dev", num_shards=None, shard_id=None, load_cache=True):   
        super().__init__("gold", dataset_name=dataset_name, split=split, num_shards=num_shards, shard_id=shard_id, load_cache=load_cache)
        # Check cache
        if self.cached_data is not None:
            self.retrieved, self.gold_patches, self.test_patches = self.cached_data
            return
        print(f"Retrieving {self.dataset.num_rows} items from {dataset_name}")
        # Retrieve the files
        self.retrieved: t.Dict[str, t.List[RetrievedFile]] = {}
        self.gold_patches: t.Dict[str, unidiff.PatchSet] = {}
        self.test_patches: t.Dict[str, unidiff.PatchSet] = {}
        for item in self.dataset:
            try:
                # Clone the repo
                repo, commit = item["repo"], item["base_commit"]
                repo_target = download_repo(repo, commit, self.repo_download_dir)
                # Parse the patch
                patch = unidiff.PatchSet(item["patch"])
                self.retrieved[item["instance_id"]] = self.read_source_patch(repo_target, patch)
                self.gold_patches[item["instance_id"]] = patch
                try:
                    self.test_patches[item["instance_id"]] = unidiff.PatchSet(item["test_patch"])
                except:
                    self.test_patches[item["instance_id"]] = None
            except Exception as e:
                # TODO: Better error handling
                print(f"Error processing {item['instance_id']}: {e}")
                self.retrieved[item["instance_id"]] = None
                self.gold_patches[item["instance_id"]] = None
                self.test_patches[item["instance_id"]] = None
        print(self.retrieved)
        print(self.gold_patches)
        print(self.test_patches)
        # Save to cache
        self.save_to_cache((self.retrieved, self.gold_patches, self.test_patches))


    def read_source_patch(self, src_dir: str, patch: unidiff.PatchSet) -> t.List[RetrievedFile]:
        retrieved = []
        for p in patch.modified_files:                
            file_path = p.source_file
            if file_path.startswith("a/"):
                file_path = file_path[2:]
            local_path = f"{src_dir}/{file_path}"  
            with open(local_path, "r") as f:
                file_content = f.read()
            lines = []
            for hunk in p:
                line_start = hunk.source_start
                source_length = hunk.source_length
                line_end = line_start + source_length
                lines.append((line_start, line_end))
            retrieved.append(
                RetrievedFile(file_path=file_path, file_content=file_content, lines=lines)
            )
        return retrieved
    
    def collect_stats(self, code_only=True):
        """Collect stats on the retrieved files."""
        # File count
        num_files = {}
        num_edits = {}
        num_lines = {}
        num_imports = {}
        # Num edits
        for k, p in self.gold_patches.items():
            if p is None:
                continue
            file_count = 0
            edit_count = 0
            line_count = 0
            import_count = 0
            for f in p.modified_files:
                # Check if file is python
                if code_only and not f.source_file.endswith(".py"):
                    continue
                file_count += 1
                for h in f:
                    edit_count += 1
                    for line in h:
                        if line.is_added or line.is_removed:
                            line_count += 1
                        if line.is_added and (line.value.startswith("import ") or line.value.startswith("from ")):
                            import_count += 1
            num_files[k] = file_count
            num_edits[k] = edit_count
            num_lines[k] = line_count
            num_imports[k] = import_count
        return {
            "num_files": num_files,
            "num_edits": num_edits,
            "num_lines": num_lines,
            "num_imports": num_imports
        }
    
    def format_for_context(self, instance_id: str, display_level: FileDisplayLevel) -> str:
        """Format the retrieved files for context."""
        retrieved = self.retrieved[instance_id]
        if retrieved is None:
            return "No files retrieved."
        return "\n".join([r.format_for_prompt(display_level=display_level) for r in retrieved])
    
    def format_tests_for_context(self, instance_id: str) -> str:
        """For the test cases for context."""
        test_patch = self.test_patches[instance_id]
        if test_patch is None:
            return "No test cases."
        return f"""
Here the test patch for the issue:

{test_patch}
""".strip()


    def get_retrieved_files(self, instance_id: str) -> t.List[RetrievedFile]:
        """Get the retrieved files for the given instance id."""
        return self.retrieved[instance_id]