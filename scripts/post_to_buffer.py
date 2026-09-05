"""
Mon/Wed/Fri Buffer poster for the iCoinPro content engine.

Picks the next post to promote from post_library.json (prioritizing newly
approved posts, then rotating through evergreen ones so nothing gets shared
too often), builds a short compliant caption, and queues it on each
configured Buffer channel via the Buffer GraphQL API.

Required secrets/env vars:
  CRYPTO_REPO         - "owner/repo" of the richard-crypto-notes site repo
  CRYPTO_REPO_TOKEN   - GitHub PAT with repo write access to that repo
  BUFFER_API_KEY      - Buffer personal access key (posts:write scope)
  BUFFER_CHANNEL_IDS  - comma-separated "service:channelId" pairs, e.g.
                        "twitter:64f1...,facebook:64f2..."
"""

import json
import os
import time
import urllib.request

from gh_utils import get_file, put_file

CRYPTO_REPO = os.environ["CRYPTO_REPO"]
CRYPTO_REPO_TOKEN = os.environ["CRYPTO_REPO_TOKEN"]
BUFFER_API_KEY = os.environ["BUFFER_API_KEY"]
BUFFER_CHANNEL_IDS = os.environ["BUFFER_CHANNEL_IDS"]

BUFFER_API_URL = "https://api.buffer.com"

# Character limits worth trimming to per platform (Buffer will reject
# over-limit text on some services, so keep captions short regardless).
PLATFORM_LIMITS = {"twitter": 260, "facebook": 500, "linkedin": 600}


def buffer_graphql(query, variables):
    req_body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        BUFFER_API_URL,
        data=req_body,
        headers={
            "Authorization": f"Bearer {BUFFER_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def create_post(channel_id, text):
    mutation = """
    mutation CreatePost($text: String!, $channelId: String!) {
      createPost(input: {
        text: $text,
        channelId: $channelId,
        schedulingType: automatic,
        mode: addToQueue
      }) {
        ... on PostActionSuccess {
          post { id text dueAt }
        }
        ... on MutationError {
          message
        }
      }
    }
    """
    result = buffer_graphql(mutation, {"text": text, "channelId": channel_id})
    return result


def pick_next_post(library):
    posts = library["posts"]
    queued = [p for p in posts if p["status"] == "queued_for_buffer"]
    if queued:
        return queued[0], "new"

    evergreen = [p for p in posts if p["status"] == "evergreen_active"]
    if not evergreen:
        return None, None
    # Rotate: pick the one least recently posted (or never posted)
    evergreen.sort(key=lambda p: p.get("last_posted_at", ""))
    return evergreen[0], "evergreen"


def build_caption(post, limit):
    disclosure = "iCoinPro affiliate here, sharing what I'm learning."
    text = f"{post['hook']} {disclosure} {post['url']}"
    if len(text) > limit:
        # Trim the hook first, keep disclosure + link intact
        overflow = len(text) - limit
        trimmed_hook = post["hook"][: max(0, len(post["hook"]) - overflow - 1)].rstrip() + "…"
        text = f"{trimmed_hook} {disclosure} {post['url']}"
    return text


def main():
    library_content, library_sha = get_file(CRYPTO_REPO, CRYPTO_REPO_TOKEN, "post_library.json")
    library = json.loads(library_content)

    post, kind = pick_next_post(library)
    if not post:
        print("No posts available to share (library is empty or misconfigured).")
        return

    channels = [pair.split(":", 1) for pair in BUFFER_CHANNEL_IDS.split(",") if pair.strip()]

    for service, channel_id in channels:
        limit = PLATFORM_LIMITS.get(service, 400)
        caption = build_caption(post, limit)
        result = create_post(channel_id, caption)
        errors = result.get("errors")
        if errors:
            print(f"Buffer error for {service}: {errors}")
        else:
            print(f"Queued on {service}: {caption}")

    # Update the library: mark as posted (new) or bump last_posted_at (evergreen)
    for p in library["posts"]:
        if p["id"] == post["id"]:
            p["status"] = "posted" if kind == "new" else "evergreen_active"
            p["last_posted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    put_file(
        CRYPTO_REPO, CRYPTO_REPO_TOKEN,
        "post_library.json", json.dumps(library, indent=2),
        f"Mark post shared to Buffer: {post['title']}", "main",
        sha=library_sha,
    )


if __name__ == "__main__":
    main()
