#!/usr/bin/env python3
"""Generate a "Most used languages" SVG card from the GitHub REST API.

Env:
  GH_TOKEN   token with repo read access (use METRICS_TOKEN to include private repos)
  GH_USER    GitHub username (default: mntgxo)
  OUT_FILE   output path (default: github-metrics-languages.svg)
  TOP_N      languages to show (default: 8)
  MAX_REPOS  optional cap on repos scanned (testing only)

Exits non-zero (and writes nothing) on any API failure or when no language
data is found, so a broken run can never replace a good card with a blank one.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from html import escape

API = "https://api.github.com"
USER = os.environ.get("GH_USER", "mntgxo")
TOKEN = os.environ.get("GH_TOKEN", "")
OUT = os.environ.get("OUT_FILE", "github-metrics-languages.svg")
TOP_N = int(os.environ.get("TOP_N", "8"))
MAX_REPOS = int(os.environ.get("MAX_REPOS", "0"))

COLORS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "HTML": "#e34c26", "CSS": "#563d7c", "PHP": "#4F5D95", "Shell": "#89e051",
    "Kotlin": "#A97BFF", "Java": "#b07219", "Dockerfile": "#384d54",
    "C": "#555555", "C++": "#f34b7d", "Go": "#00ADD8", "Rust": "#dea584",
    "Dart": "#00B4AB", "Ruby": "#701516", "Jupyter Notebook": "#DA5B0B",
    "Batchfile": "#C1F12E", "Makefile": "#427819", "SCSS": "#c6538c",
    "Vue": "#41b883", "Lua": "#000080", "Swift": "#F05138", "Other": "#8b949e",
}
FALLBACK = ["#58a6ff", "#d2a8ff", "#ffa657", "#7ee787", "#ff7b72", "#79c0ff",
            "#f2cc60", "#a5d6ff"]


def request(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "top-languages-card",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (500, 502, 503, 504) or (e.code == 403 and e.headers.get("Retry-After")):
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {url}: {last}")


def list_repos():
    if TOKEN:
        base = f"{API}/user/repos?per_page=100&affiliation=owner,collaborator,organization_member&sort=pushed"
    else:
        base = f"{API}/users/{USER}/repos?per_page=100&type=owner&sort=pushed"
    repos, page = [], 1
    while True:
        batch = request(f"{base}&page={page}")
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    # skip forks (their code isn't yours)
    repos = [r for r in repos if not r.get("fork")]
    if MAX_REPOS:
        repos = repos[:MAX_REPOS]
    return repos


def collect(repos):
    totals = {}
    for r in repos:
        try:
            langs = request(f"{API}/repos/{r['full_name']}/languages")
        except urllib.error.HTTPError as e:
            rate_limited = e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0"
            if e.code in (403, 404, 451) and not rate_limited:
                print(f"warning: skipping {r['full_name']} (HTTP {e.code})", file=sys.stderr)
                continue
            raise
        for name, size in langs.items():
            totals[name] = totals.get(name, 0) + size
    return totals


def color_for(name, i):
    return COLORS.get(name) or FALLBACK[i % len(FALLBACK)]


def render(totals):
    total = sum(totals.values())
    items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    shown = items[:TOP_N]
    rest = sum(v for _, v in items[TOP_N:])
    if rest:
        shown.append(("Other", rest))

    W, PAD = 480, 20
    BAR_W = W - 2 * PAD
    cols, row_h = 2, 24
    rows = (len(shown) + cols - 1) // cols
    H = 78 + rows * row_h + 16

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Most used languages">',
        f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="8" fill="#0d1117" stroke="#30363d"/>',
        f'<text x="{PAD}" y="32" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16" font-weight="600" fill="#58a6ff">Most used languages</text>',
        f'<clipPath id="bar"><rect x="{PAD}" y="46" width="{BAR_W}" height="8" rx="4"/></clipPath>',
        f'<g clip-path="url(#bar)"><rect x="{PAD}" y="46" width="{BAR_W}" height="8" fill="#30363d"/>',
    ]
    x = float(PAD)
    for i, (name, size) in enumerate(shown):
        w = BAR_W * size / total
        out.append(f'<rect x="{x:.2f}" y="46" width="{w:.2f}" height="8" fill="{color_for(name, i)}"/>')
        x += w
    out.append("</g>")

    col_w = (W - 2 * PAD) // cols
    for i, (name, size) in enumerate(shown):
        cx = PAD + (i % cols) * col_w
        cy = 78 + (i // cols) * row_h + 12
        pct = 100 * size / total
        out.append(f'<circle cx="{cx+5}" cy="{cy-4}" r="5" fill="{color_for(name, i)}"/>')
        out.append(
            f'<text x="{cx+18}" y="{cy}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" fill="#c9d1d9">'
            f'{escape(name)} <tspan fill="#8b949e">{pct:.1f}%</tspan></text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    repos = list_repos()
    print(f"scanning {len(repos)} repositories", file=sys.stderr)
    totals = collect(repos)
    if not totals or sum(totals.values()) == 0:
        print("error: no language data found; not writing output", file=sys.stderr)
        return 1
    svg = render(totals)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {OUT} ({len(totals)} languages)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
      
