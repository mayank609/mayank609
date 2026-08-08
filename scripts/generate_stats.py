#!/usr/bin/env python3
"""Draw stats.svg, streak.svg, langs.svg and year.svg from the GitHub GraphQL API.

Standard library only -- this runs inside GitHub Actions on the built-in
GITHUB_TOKEN, so it has no dependencies that can break in CI. See
README.md for the two determinism traps this code exists to avoid:
pin the window to whole UTC days, and only count public repositories.

Usage:
    GITHUB_TOKEN=... GH_LOGIN=octocat python3 scripts/generate_stats.py
    python3 scripts/generate_stats.py --mock   # synthetic data, no network
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from svgkit import RAMP, INK, DIM, BG, font_face, svg_document, escape  # noqa: E402

API_URL = "https://api.github.com/graphql"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
  }
}
"""

REPOS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER], privacy: PUBLIC, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def gql(query, variables, token):
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "self-generating-profile",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"GraphQL request failed: {e.code} {e.read().decode('utf-8', 'replace')}")
    if "errors" in payload:
        raise SystemExit(f"GraphQL errors: {payload['errors']}")
    return payload["data"]


def utc_window():
    """Whole-UTC-day window: [today-364d 00:00:00Z, today 23:59:59Z].

    Anchoring to day boundaries (rather than the request's wall-clock
    moment) means two runs on the same UTC day produce byte-identical
    output -- the first determinism trap in README.md.
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    to = today + timedelta(hours=23, minutes=59, seconds=59)
    frm = today - timedelta(days=364)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return frm.strftime(fmt), to.strftime(fmt), today.date()


def fetch_contributions(login, token):
    frm, to, today = utc_window()
    data = gql(CONTRIB_QUERY, {"login": login, "from": frm, "to": to}, token)
    cal = data["user"]["contributionsCollection"]["contributionCalendar"]
    days = []
    for week in cal["weeks"]:
        for d in week["contributionDays"]:
            days.append((d["date"], d["contributionCount"]))
    days.sort(key=lambda x: x[0])
    return cal["totalContributions"], days, today


def fetch_languages(login, token):
    """Aggregate language bytes across public, non-fork, owned repos only.

    A personal token also sees private repos; the Actions token doesn't.
    Restricting to PUBLIC here is the second determinism trap -- without
    it, language percentages disagree depending on who ran the script.
    """
    bytes_by_lang = {}
    repos_by_lang = {}
    colors = {}
    cursor = None
    while True:
        data = gql(REPOS_QUERY, {"login": login, "cursor": cursor}, token)
        repos = data["user"]["repositories"]
        for node in repos["nodes"]:
            seen_in_repo = set()
            for edge in node["languages"]["edges"]:
                name = edge["node"]["name"]
                bytes_by_lang[name] = bytes_by_lang.get(name, 0) + edge["size"]
                colors[name] = edge["node"]["color"] or INK
                seen_in_repo.add(name)
            for name in seen_in_repo:
                repos_by_lang[name] = repos_by_lang.get(name, 0) + 1
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]
    return bytes_by_lang, repos_by_lang


def mock_data():
    import random
    random.seed(7)
    today = datetime.now(timezone.utc).date()
    days = []
    for i in range(364, -1, -1):
        date = today - timedelta(days=i)
        weekday = date.weekday()
        base = 0 if random.random() < 0.18 else random.randint(1, 12)
        if weekday >= 5:
            base = int(base * 0.4)
        days.append((date.isoformat(), base))
    total = sum(c for _, c in days)
    bytes_by_lang = {"Python": 812_000, "TypeScript": 410_000, "JavaScript": 205_000,
                      "HTML": 88_000, "CSS": 61_000, "Shell": 22_000}
    repos_by_lang = {"Python": 9, "TypeScript": 6, "JavaScript": 5, "HTML": 3, "CSS": 3, "Shell": 4}
    return total, days, today, bytes_by_lang, repos_by_lang


# ---------------------------------------------------------------- streaks

def compute_streaks(days):
    longest = 0
    longest_range = (None, None)
    run = 0
    run_start = None
    for date, count in days:
        if count > 0:
            if run == 0:
                run_start = date
            run += 1
            if run > longest:
                longest = run
                longest_range = (run_start, date)
        else:
            run = 0

    current = 0
    current_range = (None, None)
    end_idx = len(days) - 1
    if days and days[end_idx][1] == 0:
        end_idx -= 1  # today may not have landed yet; look at yesterday
    if end_idx >= 0:
        i = end_idx
        while i >= 0 and days[i][1] > 0:
            current += 1
            i -= 1
        if current:
            current_range = (days[end_idx - current + 1][0], days[end_idx][0])
    return current, current_range, longest, longest_range


# -------------------------------------------------------------- rendering

def wipe(inner, x, y, w, h, delay=0.0, dur=0.5):
    """Reveal `inner` left-to-right once, then hold. No looping."""
    clip_id = f"clip-{abs(hash((x, y, w, h, delay))) % 999999}"
    return f"""<clipPath id="{clip_id}"><rect x="{x}" y="{y}" width="0" height="{h}">
<animate attributeName="width" from="0" to="{w}" begin="{delay:.2f}s" dur="{dur:.2f}s" fill="freeze" calcMode="spline" keySplines="0.2 0 0.2 1"/>
</rect></clipPath><g clip-path="url(#{clip_id})">{inner}</g>"""


def render_stats_svg(total, days, path):
    w, h = 480, 150
    weeks = [days[i:i + 7] for i in range(0, len(days), 7)]
    weekly = [sum(c for _, c in wk) for wk in weeks]
    peak = max(weekly) if weekly else 1
    chart_x, chart_y, chart_w, chart_h = 24, 96, w - 48, 40
    bar_w = chart_w / max(len(weekly), 1)
    points = []
    for i, v in enumerate(weekly):
        px = chart_x + i * bar_w + bar_w / 2
        py = chart_y + chart_h - (v / peak * chart_h if peak else 0)
        points.append((px, py))
    poly = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
    area = f"{chart_x:.1f},{chart_y+chart_h:.1f} " + poly + f" {chart_x+chart_w:.1f},{chart_y+chart_h:.1f}"

    css = font_face("data-bold", "jbm-b", 700) + font_face("data-regular", "jbm")
    css += f".n{{font-family:'jbm-b';font-size:44px;fill:{INK};}}"
    css += f".l{{font-family:'jbm';font-size:12px;fill:{DIM};letter-spacing:.05em;}}"
    css += f".area{{fill:{INK};fill-opacity:.12;}}.line{{fill:none;stroke:{INK};stroke-width:1.5;}}"

    body = wipe(f'<text x="24" y="52" class="n">{total:,}</text>', 24, 8, 240, 60, 0.0, 0.5)
    body += f'<text x="24" y="76" class="l">CONTRIBUTIONS - LAST 365 DAYS</text>'
    body += wipe(f'<polygon points="{area}" class="area"/><polyline points="{poly}" class="line"/>',
                 chart_x, chart_y - 8, chart_w, chart_h + 16, 0.35, 0.6)
    svg = svg_document(w, h, body, css, title=f"{total} contributions in the last 365 days")
    with open(path, "w") as f:
        f.write(svg)


def render_streak_svg(current, current_range, longest, longest_range, path):
    w, h = 480, 150
    css = font_face("data-bold", "jbm-b", 700) + font_face("data-regular", "jbm")
    css += f".n{{font-family:'jbm-b';font-size:40px;fill:{INK};}}"
    css += f".l{{font-family:'jbm';font-size:12px;fill:{DIM};letter-spacing:.05em;}}"
    css += f".r{{font-family:'jbm';font-size:12px;fill:{DIM};}}"

    def col(x, label, n, rng):
        span = f"{rng[0]} -&gt; {rng[1]}" if rng[0] else "no streak yet"
        g = f'<text x="{x}" y="52" class="n">{n}</text>'
        g += f'<text x="{x}" y="72" class="l">{escape(label)}</text>'
        g += f'<text x="{x}" y="94" class="r">{span}</text>'
        return wipe(g, x, 8, 200, 100, 0.0 if x < w / 2 else 0.25, 0.5)

    body = col(24, "CURRENT STREAK (DAYS)", current, current_range)
    body += col(w // 2 + 8, "LONGEST STREAK (DAYS)", longest, longest_range)
    body += f'<line x1="{w//2}" y1="16" x2="{w//2}" y2="{h-16}" stroke="{DIM}" stroke-opacity=".3"/>'
    svg = svg_document(w, h, body, css, title=f"current streak {current} days, longest {longest} days")
    with open(path, "w") as f:
        f.write(svg)


def render_langs_svg(bytes_by_lang, repos_by_lang, path, top_n=6):
    w = 520
    row_h = 26
    top = sorted(bytes_by_lang.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    total_bytes = sum(bytes_by_lang.values()) or 1
    h = 32 + row_h * len(top) + 16

    css = font_face("data-bold", "jbm-b", 700) + font_face("data-regular", "jbm")
    css += f".l{{font-family:'jbm';font-size:12px;fill:{DIM};letter-spacing:.05em;}}"
    css += f".name{{font-family:'jbm-b';font-size:13px;fill:{INK};}}"
    css += f".pct{{font-family:'jbm';font-size:12px;fill:{DIM};}}"
    css += f".bar-bg{{fill:{INK};fill-opacity:.10;}}.bar{{fill:{INK};}}"

    bar_x, bar_w = 150, 200
    body = f'<text x="24" y="24" class="l">TOP LANGUAGES - BY BYTES, PUBLIC REPOS</text>'
    for i, (name, size) in enumerate(top):
        y = 44 + i * row_h
        pct = size / total_bytes
        bw = bar_w * pct
        repos = repos_by_lang.get(name, 0)
        row = f'<text x="24" y="{y+14}" class="name">{escape(name)}</text>'
        row += f'<rect x="{bar_x}" y="{y+2}" width="{bar_w}" height="10" rx="2" class="bar-bg"/>'
        row += wipe(f'<rect x="{bar_x}" y="{y+2}" width="{bw:.1f}" height="10" rx="2" class="bar"/>',
                     bar_x, y, bar_w, 14, 0.05 * i, 0.45)
        row += f'<text x="{bar_x+bar_w+10}" y="{y+11}" class="pct">{pct*100:.0f}% - {repos} repo{"s" if repos != 1 else ""}</text>'
        body += row
    svg = svg_document(w, h, body, css, title="top languages by bytes across public repositories")
    with open(path, "w") as f:
        f.write(svg)


def render_year_svg(days, path):
    """One ramp character per day, quantised to the ramp's 13 levels."""
    weeks = [days[i:i + 7] for i in range(0, len(days), 7)]
    counts = [c for _, c in days]
    peak = max(counts) if counts else 1
    levels = len(RAMP) - 1

    cell = 11
    pad_l, pad_t = 16, 24
    w = pad_l + len(weeks) * cell + 16
    h = pad_t + 7 * cell + 16

    css = font_face("ramp", "jbm-r")
    css += f".l{{font-family:'jbm';font-size:12px;fill:{DIM};letter-spacing:.05em;}}"
    css += f".cell{{font-family:'jbm-r';font-size:{cell}px;fill:{INK};dominant-baseline:hanging;}}"
    css += font_face("data-regular", "jbm")

    body = f'<text x="{pad_l}" y="16" class="l">CONTRIBUTIONS - ONE CHARACTER PER DAY</text>'
    glyphs = []
    for wi, week in enumerate(weeks):
        for di, (date, count) in enumerate(week):
            level = 0 if count == 0 else max(1, round((count / peak) * levels)) if peak else 0
            ch = RAMP[min(level, levels)]
            x = pad_l + wi * cell
            y = pad_t + di * cell
            glyphs.append(f'<text x="{x}" y="{y}" class="cell">{escape(ch)}</text>')
    body += wipe("".join(glyphs), pad_l, pad_t, len(weeks) * cell, 7 * cell, 0.1, 0.9)
    svg = svg_document(w, h, body, css, title="contribution activity, one character per day for the last year")
    with open(path, "w") as f:
        f.write(svg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use synthetic data, no network calls")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()

    if args.mock:
        total, days, today, bytes_by_lang, repos_by_lang = mock_data()
    else:
        token = os.environ.get("GITHUB_TOKEN")
        login = os.environ.get("GH_LOGIN")
        if not token or not login:
            raise SystemExit("GITHUB_TOKEN and GH_LOGIN must be set (or pass --mock)")
        total, days, today = fetch_contributions(login, token)
        bytes_by_lang, repos_by_lang = fetch_languages(login, token)

    current, current_range, longest, longest_range = compute_streaks(days)

    render_stats_svg(total, days, os.path.join(args.out, "stats.svg"))
    render_streak_svg(current, current_range, longest, longest_range, os.path.join(args.out, "streak.svg"))
    render_langs_svg(bytes_by_lang, repos_by_lang, os.path.join(args.out, "langs.svg"))
    render_year_svg(days, os.path.join(args.out, "year.svg"))
    print(f"wrote stats.svg streak.svg langs.svg year.svg to {args.out}")


if __name__ == "__main__":
    main()
