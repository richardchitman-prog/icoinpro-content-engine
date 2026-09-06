"""
Weekly blog post generator for the iCoinPro content engine.

What it does:
  1. Reads config/topics_queue.json, picks the next "pending" topic.
  2. Calls the Anthropic API to draft a compliant, on-voice blog post as JSON.
  3. Creates a new branch on the crypto-notes repo with:
       - the new blog HTML file
       - an updated blog index linking to it
       - an updated post_library.json entry (status: queued_for_buffer)
  4. Opens a Pull Request for human review before it goes live.
  5. Marks the topic "drafted" in topics_queue.json (committed directly to main,
     since this file never appears on the public site).

Required secrets/env vars:
  ANTHROPIC_API_KEY   - Claude API key
  CRYPTO_REPO         - "owner/repo" of the richard-crypto-notes site repo
  CRYPTO_REPO_TOKEN   - GitHub PAT with repo write access to that repo
  ENGINE_REPO         - "owner/repo" of THIS content-engine repo (holds topics_queue.json)
  ENGINE_REPO_TOKEN   - GitHub PAT with repo write access to this repo (can be same PAT)
"""

import json
import os
import time
import urllib.request

from gh_utils import GITHUB_API, gh_request, get_file, put_file, create_branch

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CRYPTO_REPO = os.environ["CRYPTO_REPO"]
CRYPTO_REPO_TOKEN = os.environ["CRYPTO_REPO_TOKEN"]
ENGINE_REPO = os.environ["ENGINE_REPO"]
ENGINE_REPO_TOKEN = os.environ["ENGINE_REPO_TOKEN"]


def call_claude(topic, angle, links, existing_titles):
    system_prompt = f"""You are ghostwriting a blog post for Richard Chitman's personal crypto-education
blog, "Field Notes on Crypto" (an iCoinPro affiliate site). Voice: first-person, honest, understated,
"here's what I'm learning" — never hypey, never salesy.

Hard rules, no exceptions:
- NEVER state or imply specific income amounts or earnings potential.
- NEVER use recruitment pressure language ("join my team", "don't miss out", "limited spots").
- If you mention the business side at all, be direct and honest that iCoinPro pays affiliates
  through a unilevel structure — never obscure this.
- The only links you may include are: the Free Boot Camp link ({links['free_boot_camp_url']})
  for a soft/general mention, or the main site link ({links['main_site_url']}) for a full-overview
  mention. NEVER include any other funnel or "powerline" link — that link is reserved for 1-on-1
  conversations only and must never appear in public content.
- Do not repeat these existing post titles or their exact angle: {existing_titles}
- Length: 500-800 words. Plain HTML body using <p>, <h2>, <ul> as needed (no <html>/<body> tags).

Respond with ONLY valid JSON, no markdown fences, no preamble, in this exact shape:
{{
  "title": "...",
  "slug": "lowercase-hyphenated-slug",
  "meta_description": "...(under 160 chars)...",
  "body_html": "...",
  "hook_text_for_social": "...(under 200 chars, one honest hook line for a social caption)...",
  "disclosure_line": "...(one sentence disclosing this is written by an iCoinPro affiliate)..."
}}"""

    user_prompt = f"Topic: {topic}\nAngle: {angle}"

    req_body = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())

    text = "".join(block["text"] for block in data["content"] if block["type"] == "text")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def main():
    # 1. Load topics queue + links config from the engine repo
    topics_content, topics_sha = get_file(ENGINE_REPO, ENGINE_REPO_TOKEN, "config/topics_queue.json")
    topics = json.loads(topics_content)
    links_content, _ = get_file(ENGINE_REPO, ENGINE_REPO_TOKEN, "config/links.json")
    links = json.loads(links_content)

    pending = [t for t in topics if t["status"] == "pending"]
    if not pending:
        print("No pending topics left in topics_queue.json. Add more and re-run.")
        return
    topic = pending[0]

    # 2. Load existing post library for title de-duplication context
    library_content, library_sha = get_file(CRYPTO_REPO, CRYPTO_REPO_TOKEN, "post_library.json")
    library = json.loads(library_content)
    existing_titles = [p["title"] for p in library["posts"]]

    # 3. Generate the post
    post = call_claude(topic["topic"], topic["angle"], links, existing_titles)

    # 4. Build the HTML file from the template
    template_content, _ = get_file(ENGINE_REPO, ENGINE_REPO_TOKEN, "scripts/post_template.html")
    date_str = time.strftime("%B %d, %Y")
    html = (
        template_content
        .replace("{{TITLE}}", post["title"])
        .replace("{{META_DESCRIPTION}}", post["meta_description"])
        .replace("{{DATE}}", date_str)
        .replace("{{BODY_HTML}}", post["body_html"])
        .replace("{{DISCLOSURE_LINE}}", post["disclosure_line"])
    )

    branch_name = f"content/{post['slug']}"
    create_branch(CRYPTO_REPO, CRYPTO_REPO_TOKEN, branch_name)

    # 5. Commit the new post file to the branch
    put_file(
        CRYPTO_REPO, CRYPTO_REPO_TOKEN,
        f"blog/{post['slug']}.html", html,
        f"Add draft post: {post['title']}", branch_name,
    )

    # 6. Update post_library.json on the branch
    post_url = f"{links['blog_base_url']}/{post['slug']}.html"
    library["posts"].append({
        "id": post["slug"],
        "title": post["title"],
        "url": post_url,
        "hook": post["hook_text_for_social"],
        "status": "queued_for_buffer",
    })
    put_file(
        CRYPTO_REPO, CRYPTO_REPO_TOKEN,
        "post_library.json", json.dumps(library, indent=2),
        f"Queue new post for Buffer: {post['title']}", branch_name,
        sha=library_sha,
    )

    # 7. Open the PR
    pr = gh_request("POST", f"{GITHUB_API}/repos/{CRYPTO_REPO}/pulls", CRYPTO_REPO_TOKEN, {
        "title": f"[Auto-draft] {post['title']}",
        "head": branch_name,
        "base": "main",
        "body": (
            f"Auto-drafted from topic queue item `{topic['id']}`.\n\n"
            f"**Please review for compliance before merging** — check for accidental income "
            f"claims, recruitment language, or link misuse. Merging this PR publishes the post "
            f"and queues it for Buffer distribution.\n\n"
            f"Meta description: {post['meta_description']}\n\n"
            f"Suggested social hook: {post['hook_text_for_social']}"
        ),
    })
    print(f"Opened PR: {pr.get('html_url')}")

    # 8. Mark topic drafted directly on main (internal tracking file only)
    for t in topics:
        if t["id"] == topic["id"]:
            t["status"] = "drafted"
    put_file(
        ENGINE_REPO, ENGINE_REPO_TOKEN,
        "config/topics_queue.json", json.dumps(topics, indent=2),
        f"Mark topic {topic['id']} as drafted", "main",
        sha=topics_sha,
    )


if __name__ == "__main__":
    main()
