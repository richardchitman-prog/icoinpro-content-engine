import base64
import json
import sys
import urllib.request
import urllib.error

GITHUB_API = "https://api.github.com"


def gh_request(method, url, token, data=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "icoinpro-content-engine",
    }
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"GitHub API error {e.code} on {method} {url}: {e.read().decode()}", file=sys.stderr)
        raise


def get_file(repo, token, path, ref="main"):
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}?ref={ref}"
    data = gh_request("GET", url, token)
    content = base64.b64decode(data["content"]).decode()
    return content, data["sha"]


def put_file(repo, token, path, content, message, branch, sha=None):
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    return gh_request("PUT", url, token, payload)


def create_branch(repo, token, branch_name, base="main"):
    ref_data = gh_request("GET", f"{GITHUB_API}/repos/{repo}/git/ref/heads/{base}", token)
    base_sha = ref_data["object"]["sha"]
    gh_request(
        "POST",
        f"{GITHUB_API}/repos/{repo}/git/refs",
        token,
        {"ref": f"refs/heads/{branch_name}", "sha": base_sha},
    )
