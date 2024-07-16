import typing as t
import os
from common import download_repo
from common.handles import TEXT_SEARCH, REPO, CACHE
from . import CodeDisplayLevel, LineNumberMode
from .module import HighLevelModule, build_module
from itertools import chain



EXCLUDE_DIRS = [".git", ".github", "venv", "node_modules", "__pycache__"]
EXCLUDE_EXTS = [".pyc"]



def list_files(dir):
    """List all files in a directory, excluding some directories."""
    files = []
    for root, _, filenames in os.walk(dir):
        if any(exclude in root for exclude in EXCLUDE_DIRS):
            continue
        for filename in filenames:
            if any(filename.endswith(exclude) for exclude in EXCLUDE_EXTS):
                continue
            files.append(os.path.join(root, filename))
    files.sort()
    return files

def list_dirs(dir):
    """List folders"""
    dirs = set()
    for root, dirnames, _ in os.walk(dir):
        if any(exclude in root for exclude in EXCLUDE_DIRS):
            continue
        for dirname in dirnames:
            dirname = os.path.join(root, dirname)
            nice_dirname = dirname.replace(dir, "")
            if nice_dirname.startswith("/"):
                nice_dirname = nice_dirname[1:]
            if nice_dirname in EXCLUDE_DIRS:
                continue
            print(nice_dirname)
            dirs.add(nice_dirname)
    dirs = list(dirs)
    dirs.sort()
    return dirs



def make_code_search(item, check_cache=True) -> SourceCode:
    instance_id = item["instance_id"]
    cache_key = f"code_search_{instance_id}"
    if check_cache:
        cached_search = CACHE.get_object(cache_key)
        if cached_search is not None:
            (modules, raw_files, dirs) = cached_search
            return SourceCode(item, modules, raw_files, dirs)
    repo_target = REPO.download_repo(item)
    files = list_files(repo_target)
    dirs = list_dirs(repo_target)

    modules: t.Dict[str, HighLevelModule] = {}
    raw_files = {}
    for f in files:
        try:
            if f.endswith(".py"):
                module = build_module(f)
                if module is not None:
                    modules[f] = module
                else:
                    with open(f, "r") as file:
                        raw_files[f] = file.read()
            else:
                if not "README" in f:
                    # TODO: Figure out how to handle non-python and non-readme files.
                    continue
                with open(f, "r") as file:
                    raw_files[f] = file.read()
        except UnicodeError:
            # Skip files that can't be read as text.
            continue
    print(f"Modules: {len(modules)}")
    print(f"Raw files: {len(raw_files)}")
    TEXT_SEARCH.cleanup(instance_id)
    for filename, content in raw_files.items():
        filename = filename.replace(repo_target, "")
        if filename.endswith(".py"):
            elem_type = "module"
        elif "README" in filename:
            elem_type = "readme"
        else:
            elem_type = "other"
        content = f"{content}"
        TEXT_SEARCH.insert_into_db(
            instance_id=instance_id, filename=filename, elem_name=filename,
            parent_name="", display_level="", elem_type=elem_type,
            content=content
        )
    for filename, module in modules.items():
        filename = filename.replace(repo_target, "")
        module_display_levels = [CodeDisplayLevel.MINIMAL, CodeDisplayLevel.MODERATE, CodeDisplayLevel.FULL]
        for display_level in module_display_levels:
            level = display_level.value
            module_content = f"{module.display(level=display_level, line_mode=LineNumberMode.DISABLED)}"
            TEXT_SEARCH.insert_into_db(
                instance_id=instance_id, filename=filename, elem_name=filename,
                parent_name="", display_level=level, elem_type="module",
                content=module_content
            )
        # Only do minimal display for now.
        internal_display_levels = [CodeDisplayLevel.MINIMAL]
        for display_level in internal_display_levels:
            level = display_level.value
            for fn_name in module.functions:
                TEXT_SEARCH.insert_into_db(
                    instance_id=instance_id, filename=filename, elem_name=fn_name,
                    parent_name="", display_level=level, elem_type="function",
                    content=module.display_function(fn_name, level=display_level, line_mode=LineNumberMode.DISABLED)
                )
            for class_name in module.classes:
                TEXT_SEARCH.insert_into_db(
                    instance_id=instance_id, filename=filename, elem_name=class_name,
                    parent_name="", display_level=level, elem_type="class",
                    content=module.display_class(class_name, level=display_level, line_mode=LineNumberMode.DISABLED)
                )
    # Done.
    code_search = SourceCode(item, modules, raw_files, dirs)
    CACHE.set_object(cache_key, (modules, raw_files, dirs))
    return code_search


def build_dataset_index(dataset: str, split: str, repo_dir="working_stage/downloaded_repos", check_cache=True):
    """Build the code search index for a dataset."""
    import datasets
    import threading
    dataset = datasets.load_dataset(dataset, split=split)
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
            make_code_search(item, check_cache=check_cache)
    for i, chunk in enumerate(chunks):
        thread = threading.Thread(target=_build_dataset_index, args=(chunk, check_cache, i))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()