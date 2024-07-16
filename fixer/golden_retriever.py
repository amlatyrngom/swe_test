import unidiff
import git
import dotenv
import os

import unidiff.errors
from common.handles import LANGUAGE_MODEL, REPO
from fixer.module import SourceCodeIndex, CodeDisplayLevel, LineNumberMode
import typing as t



class GoldenRetriever:
    """
    Retrieves files touched by the gold patch.
    This should be the baseline. It is hard, but not impossible, to beat this retriever.
    For example it does not recursively retrieve files that are imported by the files in the gold patch.
    """
    def __init__(self):
        pass


    def retrieve_fix_context(self, code_index: SourceCodeIndex) -> str:
        try:
            # Parse the patch
            fix_context = self.read_source_patch(code_index)
        except unidiff.errors.UnidiffParseError as e:
            print(f"Error parsing patch: {e}")
            return ""
        return fix_context


    def read_source_patch(self, code_index: SourceCodeIndex) -> str:
        patch = unidiff.PatchSet(code_index.dataset_item["patch"])
        retrieved_context = []
        for p in patch.modified_files:                
            file_path = p.source_file
            if file_path.startswith("a/"):
                file_path = file_path[2:]
            if not file_path.endswith(".py"):
                continue
            module = code_index.modules[file_path]
            module_summary = module.display(level=CodeDisplayLevel.MODERATE, line_mode=LineNumberMode.ENABLED)
            if len(module_summary) > 20000:
                module_summary = module.display(level=CodeDisplayLevel.SIGNATURE, line_mode=LineNumberMode.ENABLED)
            if len(module_summary) > 20000:
                module_summary = ""
            else:
                module_summary = f"""
Here is an overview of the {file_path} file:
{module_summary}                
""".strip()
            module_subcontents = []
            module_lines = module.source_file.lines
            for hunk in p:
                line_start = hunk.source_start - 1
                source_length = hunk.source_length
                line_end = line_start + source_length
                line_start = max(0, line_start-10)
                line_end = min(len(module_lines), line_end+10)
                sublines = module_lines[line_start:line_end]
                subcontent = module.source_file.display_content(sublines, line_start, line_number_mode=LineNumberMode.ENABLED)
                module_subcontents.append(f"""
=======
Here is a relevant section of the {file_path} file. The bug is potentially in this section:
{subcontent}
=======
""".strip())
            module_subcontents = "\n".join(module_subcontents)
            retrieved_context.append(f"""
=====================
{module_summary}
{module_subcontents}
=====================
""")
        retrieved_context = "\n".join(retrieved_context)
        return retrieved_context
    
    def collect_stats(self, dataset_name, code_only=True):
        """Collect stats."""
        import datasets
        dataset = datasets.load_dataset(dataset_name)
        # File count
        num_files = {}
        num_edits = {}
        num_lines = {}
        num_imports = {}
        # Num edits
        for item in dataset:
            k = item["instance_id"]
            try:
                p = unidiff.PatchSet(item["patch"])
            except:
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
    

GOLDEN_RETRIEVER = GoldenRetriever()