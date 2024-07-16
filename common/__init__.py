import os
import git
import typing as t


def download_repo(repo, commit, download_dir, force=False) -> str:
    """Download a repository at a specific commit to a directory."""
    # Repo is in the form of "owner/repo"
    owner, repo = repo.split("/")
    github_token = os.environ.get("GITHUB_TOKEN")
    repo_url = f"https://{github_token}@github.com/{owner}/{repo}.git"
    repo_target = f"{download_dir}/{owner}__{repo}/"
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