from fastapi import FastAPI
from pydantic import BaseModel
import re
import urllib.error
import urllib.request
import json

app = FastAPI()


class RepoRequest(BaseModel):
   repo_url: str


@app.get("/")
def home():
   return {"message": "README Checker is running!"}


@app.post("/api/check-readme")
def check_readme(request: RepoRequest):
    pattern = r"^https://github\.com/([^/]+)/([^/]+)/?$"
    match = re.match(pattern, request.repo_url.strip())

    if not match:
        return {"result": "FAIL", "reason": "Invalid GitHub repository URL"}

    owner, repo = match.groups()
    repo = repo.removesuffix(".git")

    api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"

    req = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "README-Checker"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data.get("path", "").lower() == "readme.md":
                return {"result": "PASS"}

            return {
                "result": "FAIL",
                "reason": "No README.md found in the repository root"
            }

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {
                "result": "FAIL",
                "reason": "Repository or README.md not found, or repository is inaccessible"
        }

        return {
            "result": "FAIL",
            "reason": f"GitHub returned HTTP {error.code}"
    }

    except Exception:
        return {
            "result": "FAIL",
            "reason": "Could not connect to GitHub"
        }