#!/usr/bin/env python3
"""Refresh per-paper Google Scholar citation counts in scholar.json via SerpAPI.

Reads the papers already listed in scholar.json, queries the SerpAPI
Google Scholar Author API, matches each paper to a Scholar article by title,
and writes back the latest "cited by" count and link. Only rewrites the file
when something actually changed, so unchanged runs produce no commit.

Env:
  SERPAPI_KEY         SerpAPI API key (required; if empty the script no-ops).
  SCHOLAR_AUTHOR_ID   Google Scholar author id (falls back to scholar.json).
"""

import datetime
import difflib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scholar.json")
MATCH_THRESHOLD = 0.82


def norm(s):
    """Lowercase, strip punctuation, collapse whitespace — for fuzzy title matching."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def fetch_articles(author_id, key):
    """Return all articles for the author, following SerpAPI pagination."""
    articles = []
    start = 0
    while True:
        query = urllib.parse.urlencode({
            "engine": "google_scholar_author",
            "author_id": author_id,
            "api_key": key,
            "num": 100,
            "start": start,
        })
        url = "https://serpapi.com/search.json?" + query
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.load(resp)
        if data.get("error"):
            sys.exit("SerpAPI error: " + str(data["error"]))
        batch = data.get("articles") or []
        articles.extend(batch)
        if len(batch) < 100:
            return articles
        start += len(batch)


def best_match(target_title, articles):
    """Pick the article whose title best matches target_title (or None)."""
    nt = norm(target_title)
    best, best_ratio = None, 0.0
    for art in articles:
        na = norm(art.get("title", ""))
        if not na:
            continue
        if na == nt or nt in na or na in nt:
            ratio = 1.0
        else:
            ratio = difflib.SequenceMatcher(None, na, nt).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, art
    return (best, best_ratio) if best_ratio >= MATCH_THRESHOLD else (None, best_ratio)


def main():
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if not key:
        print("SERPAPI_KEY not set — skipping (add it as a repository secret to enable).")
        return

    with open(PATH, encoding="utf-8") as fh:
        data = json.load(fh)

    author_id = os.environ.get("SCHOLAR_AUTHOR_ID", "").strip() or data.get("author_id", "").strip()
    if not author_id:
        sys.exit("No Scholar author id (set SCHOLAR_AUTHOR_ID or author_id in scholar.json).")

    articles = fetch_articles(author_id, key)
    print("Fetched %d article(s) from Scholar profile %s." % (len(articles), author_id))

    changed = False
    for slug, paper in data.get("papers", {}).items():
        art, ratio = best_match(paper.get("title", ""), articles)
        if not art:
            print("  [no match %.2f] %s" % (ratio, paper.get("title", "")))
            continue
        cited_by = art.get("cited_by") or {}
        raw = cited_by.get("value")
        count = int(raw) if isinstance(raw, (int, float)) else (int(raw) if str(raw).isdigit() else 0)
        link = cited_by.get("link") or art.get("link") or paper.get("url", "")
        if paper.get("citations") != count or paper.get("url") != link:
            paper["citations"] = count
            paper["url"] = link
            changed = True
        print("  [match %.2f] %s -> %d" % (ratio, paper.get("title", ""), count))

    if not changed:
        print("No citation changes.")
        return

    data["updated"] = datetime.date.today().isoformat()
    with open(PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("Updated scholar.json.")


if __name__ == "__main__":
    main()
