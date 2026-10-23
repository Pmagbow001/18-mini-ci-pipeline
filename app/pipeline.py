from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

GITHUB_REPO_PATTERN = r"^https://github\.com/([^/]+)/([^/]+)/?$"


def _parse_repo_owner_and_name(repo_url: str) -> tuple[str, str] | None:
    cleaned = repo_url.strip()
    if not cleaned:
        return None

    match = re.match(GITHUB_REPO_PATTERN, cleaned)
    if not match:
        return None

    owner, repo = match.groups()
    repo = repo.removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def _github_request(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "README-Checker",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def check_readme(repo_url: str) -> dict[str, str]:
    repo_parts = _parse_repo_owner_and_name(repo_url)
    if repo_parts is None:
        return {"result": "FAIL", "reason": "Invalid GitHub repository URL"}

    owner, repo = repo_parts

    try:
        readme_data = _github_request(f"https://api.github.com/repos/{owner}/{repo}/readme")
        path = str(readme_data.get("path", "")).lower()
        if path == "readme.md":
            return {"result": "PASS"}
        return {"result": "FAIL", "reason": "No README.md found in the repository root"}
    except urllib.error.HTTPError as error:
        if error.code == 404:
            try:
                _github_request(f"https://api.github.com/repos/{owner}/{repo}")
                return {
                    "result": "FAIL",
                    "reason": "README.md not found in the repository root",
                }
            except urllib.error.HTTPError:
                return {
                    "result": "FAIL",
                    "reason": "Repository not found or inaccessible",
                }

        return {"result": "FAIL", "reason": f"GitHub returned HTTP {error.code}"}
    except urllib.error.URLError:
        return {"result": "FAIL", "reason": "Unable to reach GitHub API"}
