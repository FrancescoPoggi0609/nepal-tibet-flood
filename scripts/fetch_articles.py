#!/usr/bin/env python3
"""Build articles.json for the Nepal-Tibet flood page.

Two streams, kept strictly apart:

  primary     institutional and technical material - the curated entries in
              sources.json, situation reports from the ReliefWeb (UN OCHA)
              archive, and anything GDELT indexes on the domain allow-list
  secondary   general news coverage, deduplicated by outlet

Run hourly by .github/workflows/update-articles.yml.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

OUTPUT = "articles.json"
CURATED = "sources.json"
CONTACT = "francesco.poggi@example.org"   # put your real address here

MAX_PRIMARY = 30
MAX_SECONDARY = 20
PER_OUTLET = 2            # cap per outlet in the secondary list

# ---------------------------------------------------------------- allow-list

# Only these domains are accepted into the primary list from the news index.
ALLOWED = {
    "usgs.gov": "USGS", "earthquake.usgs.gov": "USGS",
    "nasa.gov": "NASA", "earthobservatory.nasa.gov": "NASA Earth Observatory",
    "disasters.nasa.gov": "NASA Disasters", "science.nasa.gov": "NASA",
    "esa.int": "ESA", "eu-space.europa.eu": "EUSPA",
    "copernicus.eu": "Copernicus", "emergency.copernicus.eu": "Copernicus EMS",
    "mapping.emergency.copernicus.eu": "Copernicus EMS",
    "rapidmapping.emergency.copernicus.eu": "Copernicus EMS",
    "icimod.org": "ICIMOD",
    "unitar.org": "UNOSAT", "unosat.org": "UNOSAT",
    "reliefweb.int": "ReliefWeb / OCHA", "unocha.org": "UN OCHA",
    "gdacs.org": "GDACS", "disasterscharter.org": "Disasters Charter",
    "eos.org": "AGU / Eos", "agu.org": "AGU", "egu.eu": "EGU",
    "copernicus.org": "Copernicus Publications",
    "nature.com": "Nature", "science.org": "Science",
    "wmo.int": "WMO", "undrr.org": "UNDRR", "unep.org": "UNEP",
    "ndrrma.gov.np": "NDRRMA", "dhm.gov.np": "DHM Nepal", "mofa.gov.np": "Government of Nepal",
    "ifrc.org": "IFRC", "who.int": "WHO", "wfp.org": "WFP", "unicef.org": "UNICEF",
    "hotosm.org": "HOT", "openstreetmap.org": "OpenStreetMap",
    "planet.com": "Planet Labs", "maxar.com": "Maxar / Vantor",
    "worldbank.org": "World Bank", "adb.org": "Asian Development Bank",
    "cas.cn": "Chinese Academy of Sciences", "cma.gov.cn": "China Meteorological Administration",
}

# ---------------------------------------------------------------- endpoints

RW_QUERY = "Nepal flood Rasuwa Trishuli Bhotekoshi glacier"
RELIEFWEB = ("https://api.reliefweb.int/v1/reports"
             "?appname=nepal-tibet-flood-map"
             "&query[value]=" + urllib.parse.quote(RW_QUERY) +
             "&query[operator]=OR"
             "&limit=40&sort[]=date.created:desc"
             "&fields[include][]=title"
             "&fields[include][]=url"
             "&fields[include][]=source.shortname"
             "&fields[include][]=date.created"
             "&fields[include][]=format.name")

GDELT_QUERY = ('(Rasuwa OR Gyirong OR "Bhote Koshi" OR Trishuli OR "Lhende" OR '
               '"Nepal flood" OR "Nepal floods" OR "glacier collapse")')
GDELT = ("https://api.gdeltproject.org/api/v2/doc/doc"
         "?query=" + urllib.parse.quote(GDELT_QUERY) +
         "&mode=ArtList&format=json&maxrecords=250&timespan=14d&sort=DateDesc")


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"nepal-tibet-flood-map/3.0 (GitHub Actions; mailto:{CONTACT})"
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def host(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def label_for(domain):
    if domain in ALLOWED:
        return ALLOWED[domain]
    for known, name in ALLOWED.items():
        if domain.endswith("." + known):
            return name
    return None


# ---------------------------------------------------------------- collectors

def load_curated():
    if not os.path.exists(CURATED):
        return []
    try:
        with open(CURATED, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"Could not read {CURATED}: {exc}", file=sys.stderr)
        return []
    out = []
    for s in data.get("sources", []):
        if s.get("url") and s.get("title"):
            out.append({
                "title": s["title"], "url": s["url"],
                "org": s.get("org") or label_for(host(s["url"])) or host(s["url"]),
                "note": s.get("note", ""), "date": s.get("date", ""),
            })
    return out


def reliefweb(seen):
    """Situation reports and assessments filed with UN OCHA."""
    try:
        data = get(RELIEFWEB)
    except Exception as exc:
        print(f"ReliefWeb request failed: {exc}", file=sys.stderr)
        return []
    out = []
    for item in data.get("data") or []:
        f = item.get("fields") or {}
        url = (f.get("url") or "").strip()
        title = (f.get("title") or "").strip()
        if not url or not title or url in seen:
            continue
        seen.add(url)
        src = f.get("source") or []
        org = src[0].get("shortname") if src else "ReliefWeb"
        fmt = (f.get("format") or [{}])[0].get("name", "")
        created = (f.get("date") or {}).get("created", "")[:10]
        out.append({
            "title": title, "url": url, "org": org,
            "note": fmt, "date": created,
        })
    return out


def gdelt_split(seen):
    """Return (allow-listed institutional hits, general news)."""
    try:
        data = get(GDELT)
    except Exception as exc:
        print(f"GDELT request failed: {exc}", file=sys.stderr)
        return [], []
    inst, news, per_outlet = [], [], {}
    for a in data.get("articles") or []:
        url = (a.get("url") or "").strip()
        title = (a.get("title") or "").strip()
        if not url or not title or url in seen:
            continue
        dom = host(url)
        s = str(a.get("seendate") or "")
        when = f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else ""
        org = label_for(dom)
        if org:
            seen.add(url)
            inst.append({"title": title, "url": url, "org": org, "note": "", "date": when})
            continue
        if len(news) >= MAX_SECONDARY:
            continue
        if per_outlet.get(dom, 0) >= PER_OUTLET:
            continue
        per_outlet[dom] = per_outlet.get(dom, 0) + 1
        seen.add(url)
        news.append({"title": title, "url": url, "org": dom, "note": "", "date": when})
    return inst, news


def main():
    curated = load_curated()
    seen = {s["url"] for s in curated}

    rw = reliefweb(seen)
    inst, news = gdelt_split(seen)

    primary = (curated + inst + rw)[:MAX_PRIMARY]
    secondary = news[:MAX_SECONDARY]

    if not primary and not secondary:
        print("Nothing collected; leaving the previous file in place", file=sys.stderr)
        return 1

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "primary": primary,
        "secondary": secondary,
    }

    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("primary") == primary and old.get("secondary") == secondary:
                print("No change; nothing to commit")
                return 0
        except Exception:
            pass

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(primary)} primary and {len(secondary)} secondary entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
