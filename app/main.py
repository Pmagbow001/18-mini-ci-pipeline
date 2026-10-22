from fastapi import FastAPI
from pydantic import BaseModel
import re
import urllib.error
import urllib.request
import json
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class RepoRequest(BaseModel):
   repo_url: str


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


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
            repo_check_url = f"https://api.github.com/repos/{owner}/{repo}"
            repo_req = urllib.request.Request(
            repo_check_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "README-Checker"
            }
        )

        try:
            with urllib.request.urlopen(repo_req, timeout=10):
                return {
                    "result": "FAIL",
                    "reason": "README.md not found in the repository root"
                }
        except urllib.error.HTTPError:
            return {
                "result": "FAIL",
                "reason": "Repository not found or inaccessible"
            }

    return {
        "result": "FAIL",
        "reason": f"GitHub returned HTTP {error.code}"
    }