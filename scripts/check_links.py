"""
Check every outbound link the atlas ships, and write down what happened.

A link is a claim: "this page exists and it is about what we said". Pages move.
In September 2026 six of the eight law links in the preferential-access section
pointed at an FAO host that had stopped answering, and nothing in the build
noticed. This script is the thing that would have.

It reads links from three places:

  data/org_links.json          hand-checked pages for organisations
  site/data/paa.json           the access-area laws
  site/index.html              the fixed links in source notes

and sorts each into one of three piles:

  ok        answered 200 (after redirects)
  blocked   the site refuses scripts (401 / 403 / 429 / 999), or hangs up on them
            without answering. FAOLEX, a few banks and several ministries do this.
            The link probably works in a browser, so it is kept, and recorded as
            unchecked rather than as good.
  dead      404, 410, a server error, or a domain that no longer exists

Outputs data/link_check.json. build_profile.py reads it and leaves out any
organisation link in the dead pile, so a broken page never reaches the site.

Run it before a rebuild:   python3 scripts/check_links.py
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "link_check.json")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
      "Accept-Language": "en"}
BLOCKED = {401, 403, 405, 406, 429, 451, 999}
# Hosts known to refuse scripts outright; no point knocking.
NEVER_ANSWERS_SCRIPTS = ("fao.org/faolex", "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com")


def collect():
    found = {}   # url -> where it is used

    def add(url, where):
        if url and re.match(r"^https?://", url):
            found.setdefault(url.strip(), set()).add(where)

    p = os.path.join(HERE, "data", "org_links.json")
    if os.path.exists(p):
        d = json.load(open(p))
        for table in ("by_name", "annex"):
            for key, rec in (d.get(table) or {}).items():
                add(rec.get("site"), f"organisation: {key}")
                add(rec.get("ssf"), f"organisation: {key}")

    p = os.path.join(HERE, "site", "data", "paa.json")
    if os.path.exists(p):
        for iso, rec in json.load(open(p)).get("countries", {}).items():
            for url in re.findall(r"https?://[^\s\"'<>)]+", json.dumps(rec.get("law") or "")):
                add(url.rstrip(".,"), f"access law: {iso}")

    p = os.path.join(HERE, "site", "index.html")
    if os.path.exists(p):
        # links a reader can click, not the font and script addresses in the page head
        for url in re.findall(r"<a\s[^>]*?href=\"(https?://[^\"$]+)\"", open(p, encoding="utf-8").read()):
            add(url, "page")
    return found


# Pages that are certainly up. If these cannot be reached, the problem is this
# machine's connection, not the links, and nothing is written.
CONTROLS = ("https://www.wikipedia.org/", "https://www.google.com/", "https://www.fao.org/home/en")


def online():
    ok = 0
    for url in CONTROLS:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA, method="GET"), timeout=15):
                ok += 1
        except urllib.error.HTTPError:
            ok += 1                      # any HTTP answer at all means we are online
        except Exception:
            pass
    return ok >= 2


def check(url):
    if any(h in url for h in NEVER_ANSWERS_SCRIPTS):
        return url, {"class": "blocked", "status": None, "note": "host refuses scripts; not tested"}
    ctx = ssl.create_default_context()
    last = None
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=UA, method=method)
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                return url, {"class": "ok", "status": r.status, "final": r.geturl()}
        except urllib.error.HTTPError as e:
            last = e.code
            if e.code in BLOCKED and method == "GET":
                return url, {"class": "blocked", "status": e.code}
            if e.code in (404, 410) and method == "GET":
                return url, {"class": "dead", "status": e.code}
        except Exception as e:                       # DNS failure, timeout, reset, TLS error
            text = str(getattr(e, "reason", e)).lower()
            gone = any(t in text for t in ("nodename nor servname", "name or service not known",
                                           "no address associated", "getaddrinfo failed"))
            last = "no such host" if gone else "no answer"
    if last in BLOCKED:
        return url, {"class": "blocked", "status": last}
    # No HTTP answer at all. A domain that no longer exists is dead, but that is also
    # what a dropped connection looks like, so it is tried again at the end once this
    # machine is known to be online. A timeout or a cut connection is NOT proof of
    # death: Australia's DFAT site hangs up on scripts and works fine in a browser.
    if isinstance(last, int):
        return url, {"class": "dead", "status": last}
    return url, {"class": "unreachable", "status": last}


def main():
    links = collect()
    if not online():
        print("This machine looks offline (the control pages did not answer). Nothing checked, nothing written.")
        return 1
    print(f"Checking {len(links)} links")
    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (url, res) in enumerate(pool.map(check, sorted(links)), 1):
            res["used_by"] = sorted(links[url])[:4]
            results[url] = res
            if i % 50 == 0 or i == len(links):
                print(f"  {i}/{len(links)}")

    # Second look at everything that gave no answer, once we know the connection held.
    retry = [u for u, r in results.items() if r["class"] == "unreachable"]
    if retry:
        if not online():
            print("The connection dropped during the check. Nothing written; run it again.")
            return 1
        print(f"  trying {len(retry)} unanswered links again")
        time.sleep(5)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for url, res in pool.map(check, retry):
                res["used_by"] = results[url]["used_by"]
                if res["class"] == "unreachable":
                    # twice, while online: a vanished domain is dead; silence is only unchecked
                    res["class"] = "dead" if res["status"] == "no such host" else "blocked"
                    if res["class"] == "blocked":
                        res["note"] = "gave a script no answer; not proof the page is gone"
                results[url] = res
        if not online():
            print("The connection dropped during the retry. Nothing written; run it again.")
            return 1

    tally = {}
    for r in results.values():
        tally[r["class"]] = tally.get(r["class"], 0) + 1
    with open(OUT, "w") as f:
        json.dump({"checked": time.strftime("%Y-%m-%d"), "tally": tally, "links": results}, f, indent=1)

    print(f"\n  ok {tally.get('ok', 0)} · blocked to scripts {tally.get('blocked', 0)} · dead {tally.get('dead', 0)}")
    dead = [(u, r) for u, r in results.items() if r["class"] == "dead"]
    if dead:
        print("\n  dead links (left out of the organisation directory at the next build):")
        for u, r in sorted(dead):
            print(f"    {r['status']!s:<18} {u[:90]}   <- {r['used_by'][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
