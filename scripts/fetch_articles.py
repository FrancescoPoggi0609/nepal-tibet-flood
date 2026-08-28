#!/usr/bin/env python3
"""Fetch event coverage from the GDELT DOC 2.0 API and write articles.json.

Runs inside GitHub Actions, so the request is made server-side and is not
subject to the browser cross-origin restriction that blocks the same call
from the page itself.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

QUERY = ('("Nepal flood" OR "Nepal floods" OR "Nepal Tibet" OR Rasuwa OR Gyirong OR '
         '"Bhote Koshi" OR Trishuli OR "glacier collapse" OR "Lhende")')

TIMESPAN = "7d"      # how far back to look
MAX_ARTICLES = 24    # total kept
PER_OUTLET = 2       # cap per domain, so one agency cannot fill the list
OUTPUT = "articles.json"

API = ("https://api.gdeltproject.org/api/v2/doc/doc"
       "?query=" + urllib.parse.quote(QUERY) +
       "&mode=ArtList&format=json&maxrecords=150"
       "&timespan=" + TIMESPAN + "&sort=DateDesc")


def fetch():
    req = urllib.request.Request(API, headers={
        "User-Agent": "nepal-tibet-flood-map/1.0 (GitHub Actions; static site)"
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def when(seendate):
    """GDELT stamps look like 20260826T083700Z."""
    s = str(seendate or "")
    if len(s) < 13:
        return ""
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[9:11]}:{s[11:13]}"


def normalize(raw):
    seen_urls = set()
    per_domain = {}
    out = []
    for a in raw or []:
        url = (a.get("url") or "").strip()
        title = (a.get("title") or "").strip()
        if not url or not title or url in seen_urls:
            continue
        dom = (a.get("domain") or "").lower()
        if per_domain.get(dom, 0) >= PER_OUTLET:
            continue
        per_domain[dom] = per_domain.get(dom, 0) + 1
        seen_urls.add(url)
        out.append({
            "title": title,
            "url": url,
            "src": dom,
            "when": when(a.get("seendate")),
        })
        if len(out) >= MAX_ARTICLES:
            break
    return out


def main():
    try:
        data = fetch()
    except Exception as exc:
        print(f"GDELT request failed: {exc}", file=sys.stderr)
        return 1

    articles = normalize(data.get("articles"))
    if not articles:
        print("GDELT returned no usable articles; leaving the previous file in place",
              file=sys.stderr)
        return 1

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(articles),
        "articles": articles,
    }

    # Skip the write when only the timestamp would change, so the repository
    # does not collect an empty commit every hour.
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("articles") == articles:
                print("No change in the article list; nothing to commit")
                return 0
        except Exception:
            pass

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(articles)} articles to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
