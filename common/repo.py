from common.language_model import LANGUAGE_MODEL
import os
import git
from swebench.harness.utils import extract_minimal_patch
import typing as t

class Repo:
    def __init__(self):
        config = LANGUAGE_MODEL.config
        self.github_token = os.environ.get("GITHUB_TOKEN")
        working_stage = config["working_stage"]
        self.download_dir = f"{working_stage}/downloaded_repos"
        self.verbose = config["verbose"]

    def download_repo(self, item: t.Dict[str, t.Any], force=False) -> str:
        """Download a repository at a specific commit."""
        # Repo is in the form of "owner/repo"
        repo = item["repo"]
        commit = item["base_commit"]
        owner, repo = repo.split("/")
        github_token = os.environ.get("GITHUB_TOKEN")
        repo_url = f"https://{github_token}@github.com/{owner}/{repo}.git"
        repo_target = f"{self.download_dir}/{owner}__{repo}/"
        if os.path.exists(repo_target) and force:
            print(f"Repo {owner}/{repo} already exists at {repo_target}. Removing it.")
            assert len(repo_target) > 10 # Just to be sure
            os.system(f"rm -rf '{repo_target}'")
        if not os.path.exists(repo_target):
            print(f"Clone {owner}/{repo} to {repo_target}")
            git.Repo.clone_from(repo_url, repo_target)
        print(f"Reset {owner}/{repo} to commit {commit}")
        repo = git.Repo(repo_target)
        repo.git.reset("--hard", commit)
        repo.git.clean("-fdxq")
        return repo_target


    def _check_patch_applies(self, repo: git.Repo, item: t.Dict[str, t.Any], patch, relaxed) -> t.Optional[str]:
        """
        Check if a patch applies cleanly. Return the final patch (potentially tweaked) if it does.
        When relaxed is True, the patch is applied with relaxed settings.
        The final result should pass without the relaxed settings.
        """
        patch_file = f"working_stage/check__{item['instance_id']}.patch"
        commit = item["base_commit"]
        abs_patch_path = os.path.abspath(patch_file)
        with open(abs_patch_path, "w") as f:
            f.write(patch)
        try:
            args = [abs_patch_path]
            if self.verbose:
                args.append("-v")
            if relaxed:
                args.extend(["--unidiff-zero", "--whitespace=fix"])
            repo.git.apply(*args)
            final_patch = repo.git.diff()
        except Exception as e:
            final_patch = None
        repo.git.reset("--hard", commit)
        return final_patch
    

    def check_validity(self, item: t.Dict[str, t.Any], patch: str) -> t.Optional[str]:
        """Check if a patch is valid. Return the patch if it is, None otherwise."""
        repo_target = self.download_repo(item)
        repo = git.Repo(repo_target)
        # Relaxed try in case minor tweaks are needed.
        final_patch = self._check_patch_applies(repo, item, patch, relaxed=True)
        if final_patch is None:
            return None
        # Stricter try to ensure the patch is valid.
        ok = self._check_patch_applies(repo, item, final_patch, relaxed=False)
        if ok is None:
            # Try adding a newline at the end if the strict check fails, then try again.
            final_patch += "\n"
            ok = self._check_patch_applies(repo, item, final_patch, relaxed=False)
        if ok is None:
            return None
        return final_patch
    


    def remove_whitespace(self, patch: str):
        from_str, to_str = "\n\n@@", "\n@@"
        while from_str in patch:
            patch = patch.replace(from_str, to_str)
        return patch


    def explore_valid_patch(self, item: t.Dict[str, t.Any], default_patch: str) -> t.Optional[str]:
        minimal_patch = extract_minimal_patch(default_patch)
        default_no_whitespace = self.remove_whitespace(default_patch)
        minimal_no_whitespace = self.remove_whitespace(minimal_patch)
        possibilities = [
            ("default", default_patch),
            ("minimal", minimal_patch),
            ("default_no_whitespace", default_no_whitespace),
            ("minimal_no_whitespace", minimal_no_whitespace),
        ]
        for _name, patch in possibilities:
            valid_patch = self.check_validity(item, patch)
            if valid_patch is not None:
                return valid_patch
        return None
    
REPO = Repo()