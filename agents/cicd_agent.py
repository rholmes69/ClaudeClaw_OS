"""CI/CD Agent

Handles: Git repository operations and GitHub API interactions.

Tools:
  - git_status   : Show working tree status of a local repo
  - git_pull     : Pull latest changes from remote
  - git_push     : Push committed changes to remote
  - git_clone    : Clone a GitHub repository locally
  - git_commit   : Stage all changes and create a commit
  - git_branch   : Create or list branches
  - git_checkout : Switch to an existing or new branch
  - github_create_pr   : Open a pull request via the GitHub API
  - github_list_repos  : List repositories for a GitHub user/org
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL         = "claude-sonnet-4-6"
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")
GITHUB_API    = "https://api.github.com"
_MAX_ROUNDS   = 10

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

CICD_TOOLS = [
    {
        "name": "git_status",
        "description": "Show the working tree status of a local Git repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute or relative path to the local repo."},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "git_pull",
        "description": "Pull the latest changes from the remote (origin) for the current branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the local repo."},
                "remote":    {"type": "string", "description": "Remote name. Defaults to 'origin'.", "default": "origin"},
                "branch":    {"type": "string", "description": "Branch to pull. Defaults to current branch.", "default": ""},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "git_push",
        "description": "Push committed changes to the remote repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path":    {"type": "string", "description": "Path to the local repo."},
                "remote":       {"type": "string", "description": "Remote name. Defaults to 'origin'.", "default": "origin"},
                "branch":       {"type": "string", "description": "Branch to push. Defaults to current branch.", "default": ""},
                "set_upstream": {"type": "boolean", "description": "Pass --set-upstream on first push of a new branch.", "default": False},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "git_clone",
        "description": "Clone a GitHub repository to a local directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_url":   {"type": "string", "description": "HTTPS URL of the repository to clone."},
                "dest_path":  {"type": "string", "description": "Local directory to clone into. Defaults to repo name in current directory.", "default": ""},
            },
            "required": ["repo_url"],
        },
    },
    {
        "name": "git_commit",
        "description": "Stage all changes (git add -A) and create a commit with the given message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the local repo."},
                "message":   {"type": "string", "description": "Commit message."},
            },
            "required": ["repo_path", "message"],
        },
    },
    {
        "name": "git_branch",
        "description": "List all branches or create a new branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path":   {"type": "string", "description": "Path to the local repo."},
                "branch_name": {"type": "string", "description": "Name of the branch to create. Leave empty to list existing branches.", "default": ""},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "git_checkout",
        "description": "Switch to an existing branch, or create and switch to a new one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path":   {"type": "string", "description": "Path to the local repo."},
                "branch_name": {"type": "string", "description": "Branch name to check out."},
                "create_new":  {"type": "boolean", "description": "Pass -b to create the branch if it does not exist.", "default": False},
            },
            "required": ["repo_path", "branch_name"],
        },
    },
    {
        "name": "github_create_pr",
        "description": "Open a pull request on GitHub via the API.",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner":      {"type": "string", "description": "GitHub username or organisation that owns the repo."},
                "repo":       {"type": "string", "description": "Repository name (without owner prefix)."},
                "title":      {"type": "string", "description": "Pull request title."},
                "body":       {"type": "string", "description": "Pull request description / body.", "default": ""},
                "head":       {"type": "string", "description": "The branch containing the changes (source branch)."},
                "base":       {"type": "string", "description": "The branch to merge into. Defaults to 'main'.", "default": "main"},
                "draft":      {"type": "boolean", "description": "Open as a draft PR.", "default": False},
            },
            "required": ["owner", "repo", "title", "head"],
        },
    },
    {
        "name": "github_list_repos",
        "description": "List GitHub repositories for a user or organisation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "GitHub username or organisation name."},
                "limit": {"type": "integer", "description": "Max number of repos to return. Default 20.", "default": 20},
            },
            "required": ["owner"],
        },
    },
]

SYSTEM_PROMPT = """You are the CI/CD Agent of the ClaudeClaw Council — POLAR instance.

Your domain is Git repository management and GitHub operations. You handle:
- Cloning, pulling, and pushing code repositories
- Staging and committing local changes
- Creating and switching branches
- Opening pull requests on GitHub
- Listing and inspecting GitHub repositories

You have tools for all Git and GitHub operations. Always use the appropriate tool —
never describe an action without executing it.

Workflow rules:
1. For push operations — run git_status first so you know what will be pushed.
2. For new branches — use git_branch to create, then git_checkout to switch.
3. For PRs — confirm the head branch has been pushed before calling github_create_pr.
4. Never output or log GitHub tokens, credentials, or secrets in any field.

Voice: Direct and technical. State what was done and the outcome.

Output format (always respond in JSON):
{
  "response": "Human-readable result for the user",
  "summary": "One-line summary of the operation",
  "repo": "repo name or path",
  "operation": "clone|pull|push|commit|branch|checkout|pr|status|list",
  "outcome": "success|failure|partial",
  "memory_entries": [{"category": "fact|preference|context", "key": "...", "value": "..."}]
}
"""


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str) -> dict:
    """Run a git command in cwd. Returns {stdout, stderr, returncode}."""
    # Validate path exists
    if not Path(cwd).exists():
        return {"stdout": "", "stderr": f"Path does not exist: {cwd}", "returncode": 1}
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "stdout":     result.stdout.strip(),
            "stderr":     result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Git command timed out after 60s.", "returncode": 1}
    except FileNotFoundError:
        return {"stdout": "", "stderr": "Git is not installed or not on PATH.", "returncode": 1}


def _github_request(method: str, endpoint: str, payload: Optional[dict] = None) -> dict:
    """Make an authenticated GitHub API request using urllib (no requests dep)."""
    import urllib.request
    import urllib.error

    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN not set. Add it to your .env file."}

    url = f"{GITHUB_API}{endpoint}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type":  "application/json",
    }
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return {"error": json.loads(body).get("message", body), "status": e.code}
        except Exception:
            return {"error": body, "status": e.code}
    except Exception as ex:
        return {"error": str(ex)}


def execute_cicd_tool(name: str, inputs: dict) -> str:
    """Dispatch a tool call and return a string result for the model."""

    if name == "git_status":
        r = _run_git(["status"], cwd=inputs["repo_path"])
        if r["returncode"] != 0:
            return f"ERROR: {r['stderr']}"
        return r["stdout"] or "Nothing to report — working tree clean."

    if name == "git_pull":
        args = ["pull", inputs.get("remote", "origin")]
        if inputs.get("branch"):
            args.append(inputs["branch"])
        r = _run_git(args, cwd=inputs["repo_path"])
        if r["returncode"] != 0:
            return f"ERROR: {r['stderr']}"
        return r["stdout"] or "Already up to date."

    if name == "git_push":
        args = ["push"]
        if inputs.get("set_upstream"):
            args += ["--set-upstream"]
        args.append(inputs.get("remote", "origin"))
        if inputs.get("branch"):
            args.append(inputs["branch"])
        r = _run_git(args, cwd=inputs["repo_path"])
        if r["returncode"] != 0:
            return f"ERROR: {r['stderr']}"
        return r["stdout"] or r["stderr"] or "Push successful."

    if name == "git_clone":
        repo_url  = inputs["repo_url"]
        dest      = inputs.get("dest_path", "")
        args      = ["clone", repo_url]
        if dest:
            args.append(dest)
        cwd = str(Path(dest).parent) if dest else "."
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return f"ERROR: {result.stderr.strip()}"
            return result.stderr.strip() or "Clone successful."
        except Exception as ex:
            return f"ERROR: {ex}"

    if name == "git_commit":
        # Stage everything then commit
        stage = _run_git(["add", "-A"], cwd=inputs["repo_path"])
        if stage["returncode"] != 0:
            return f"ERROR staging: {stage['stderr']}"
        commit = _run_git(["commit", "-m", inputs["message"]], cwd=inputs["repo_path"])
        if commit["returncode"] != 0:
            return f"ERROR committing: {commit['stderr']}"
        return commit["stdout"] or "Committed."

    if name == "git_branch":
        branch_name = inputs.get("branch_name", "")
        if branch_name:
            r = _run_git(["branch", branch_name], cwd=inputs["repo_path"])
            if r["returncode"] != 0:
                return f"ERROR: {r['stderr']}"
            return f"Branch '{branch_name}' created."
        r = _run_git(["branch", "-a"], cwd=inputs["repo_path"])
        return r["stdout"] or "No branches found."

    if name == "git_checkout":
        args = ["checkout"]
        if inputs.get("create_new"):
            args.append("-b")
        args.append(inputs["branch_name"])
        r = _run_git(args, cwd=inputs["repo_path"])
        if r["returncode"] != 0:
            return f"ERROR: {r['stderr']}"
        return r["stdout"] or r["stderr"] or f"Switched to branch '{inputs['branch_name']}'."

    if name == "github_create_pr":
        payload = {
            "title": inputs["title"],
            "body":  inputs.get("body", ""),
            "head":  inputs["head"],
            "base":  inputs.get("base", "main"),
            "draft": inputs.get("draft", False),
        }
        owner = inputs["owner"]
        repo  = inputs["repo"]
        resp  = _github_request("POST", f"/repos/{owner}/{repo}/pulls", payload)
        if "error" in resp:
            return f"ERROR: {resp['error']}"
        return json.dumps({
            "pr_number": resp.get("number"),
            "url":       resp.get("html_url"),
            "state":     resp.get("state"),
            "title":     resp.get("title"),
        })

    if name == "github_list_repos":
        owner = inputs["owner"]
        limit = inputs.get("limit", 20)
        resp  = _github_request("GET", f"/users/{owner}/repos?per_page={limit}&sort=updated")
        if isinstance(resp, dict) and "error" in resp:
            # Try orgs endpoint as fallback
            resp = _github_request("GET", f"/orgs/{owner}/repos?per_page={limit}&sort=updated")
        if isinstance(resp, dict) and "error" in resp:
            return f"ERROR: {resp['error']}"
        repos = [
            {"name": r["name"], "url": r["html_url"], "private": r["private"],
             "default_branch": r["default_branch"], "updated_at": r["updated_at"][:10]}
            for r in (resp if isinstance(resp, list) else [])
        ]
        return json.dumps(repos)

    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class CICDAgent:
    """Manages Git repositories and GitHub operations for ClaudeClaw OS."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def receive(self, task: dict) -> dict:
        start       = time.monotonic()
        instruction = task.get("instruction", "")
        context     = task.get("hive_context", "")

        messages = [
            {
                "role": "user",
                "content": (
                    f"{context}\n\nCI/CD task: {instruction}"
                    if context else
                    f"CI/CD task: {instruction}"
                ),
            }
        ]

        response = None
        for _ in range(_MAX_ROUNDS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=CICD_TOOLS,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = execute_cicd_tool(block.name, block.input)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     str(output),
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",       "content": tool_results})

        # Extract final text response
        raw = ""
        for block in (response.content if response else []):
            if hasattr(block, "text"):
                raw = block.text
                break

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0].strip()

        try:
            result = json.loads(cleaned)
        except Exception:
            result = {
                "response":      raw,
                "summary":       "CI/CD operation completed.",
                "repo":          "",
                "operation":     "unknown",
                "outcome":       "success",
                "memory_entries": [],
            }

        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        return result
