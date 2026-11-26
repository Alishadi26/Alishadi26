"""Generates the terminal-style SVGs for the GitHub profile README.

  assets/contributions.svg  ->  ./contributions.sh  (heatmap)
  assets/whoami.svg         ->  whoami  (ASCII portrait + stats + monthly bars)

Runs daily in GitHub Actions. Needs GITHUB_TOKEN (provided automatically).
Local preview without a token:  python scripts/generate.py --mock
Put a photo at assets/portrait.png (or .jpg) to use it for the ASCII portrait;
otherwise your GitHub avatar is used.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import random
import sys
import urllib.request
from html import escape
from pathlib import Path

USER = os.getenv("GH_USER", "Alishadi26")
HANDLE = USER.lower()
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ---- theme -----------------------------------------------------------------
BG, PANEL, BORDER = "#0d1117", "#161b22", "#30363d"
TEXT, MUTED, ACCENT = "#e6edf3", "#7d8590", "#3fb950"
LEVELS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
FONT = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"
W = 900


# ---- data ------------------------------------------------------------------
def fetch_days() -> list[tuple[dt.date, int]]:
    token = os.environ["GITHUB_TOKEN"]
    query = """query($login:String!){user(login:$login){contributionsCollection{
      contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}"""
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [(dt.date.fromisoformat(d["date"]), d["contributionCount"])
            for w in weeks for d in w["contributionDays"]]


def mock_days() -> list[tuple[dt.date, int]]:
    rnd = random.Random(26)
    end = dt.date.today()
    start = end - dt.timedelta(days=364 + (end.weekday() + 1) % 7)
    out, d = [], start
    while d <= end:
        c = 0
        if d.month in (9, 11) and rnd.random() < 0.25:
            c = rnd.randint(1, 6)
        elif rnd.random() < 0.02:
            c = rnd.randint(1, 3)
        out.append((d, c))
        d += dt.timedelta(days=1)
    return out


def compute_stats(days):
    today = days[-1][0]
    counts = {d: c for d, c in days}
    total = sum(counts.values())
    active = sum(1 for c in counts.values() if c)

    # current streak: allow today to be empty (the day isn't over yet)
    cur, d = 0, today if counts.get(today) else today - dt.timedelta(days=1)
    cur_end = d
    while counts.get(d):
        cur += 1
        d -= dt.timedelta(days=1)
    cur_start = d + dt.timedelta(days=1)

    best = run = 0
    best_range = run_start = None
    for d, c in days:
        if c:
            run_start = run_start if run else d
            run += 1
            if run > best:
                best, best_range = run, (run_start, d)
        else:
            run = 0

    best_day = max(days, key=lambda x: x[1])

    months: list[tuple[str, int]] = []
    y, m = today.year, today.month
    for _ in range(12):
        s = sum(c for d, c in days if d.year == y and d.month == m)
        months.append((dt.date(y, m, 1).strftime("%b")[0], s))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()

    return dict(
        total=total, active=active, span=len(days),
        cur=cur, cur_range=(cur_start, cur_end) if cur else None,
        best=best, best_range=best_range,
        best_day=best_day, avg=(total / active) if active else 0,
        months=months,
    )


# ---- svg helpers -----------------------------------------------------------
def fmt(d: dt.date) -> str:
    return d.strftime("%b %-d")


def window(width, height, title, body) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="{FONT}" xml:space="preserve">
<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
<path d="M0.5 36 H{width-0.5}" stroke="{BORDER}"/>
<circle cx="20" cy="18" r="6" fill="#ff5f56"/><circle cx="40" cy="18" r="6" fill="#ffbd2e"/><circle cx="60" cy="18" r="6" fill="#27c93f"/>
<text x="{width/2}" y="23" fill="{MUTED}" font-size="12" text-anchor="middle">{escape(title)}</text>
{body}
</svg>"""


def prompt(x, y, cmd, size=15) -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="700">'
            f'<tspan fill="{ACCENT}">{HANDLE}@github</tspan><tspan fill="{MUTED}"> ~ $ </tspan>'
            f'<tspan fill="{TEXT}">{escape(cmd)}</tspan></text>')


def cursor(x, y) -> str:
    return (f'<rect x="{x}" y="{y-12}" width="8" height="15" fill="{ACCENT}">'
            f'<animate attributeName="opacity" values="1;1;0;0" dur="1.1s" repeatCount="indefinite"/></rect>')


def level(c, mx):
    if c == 0:
        return 0
    return min(4, 1 + int(3 * c / max(mx, 1)))


# ---- contributions.svg -----------------------------------------------------
def contributions_svg(days, st) -> str:
    cell, gap = 12, 3
    left, top = 60, 92
    start = days[0][0]
    offset = (start.weekday() + 1) % 7  # Sunday-first rows
    mx = max(c for _, c in days) or 1
    cells, months_seen = [], {}
    for i, (d, c) in enumerate(days):
        idx = i + offset
        col, row = idx // 7, idx % 7
        x, y = left + col * (cell + gap), top + row * (cell + gap)
        tip = f"{c} contribution{'s' if c != 1 else ''} on {fmt(d)}"
        cells.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" '
                     f'fill="{LEVELS[level(c, mx)]}"><title>{tip}</title></rect>')
        if d.day <= 7 and row == 0 or i == 0:
            months_seen.setdefault((d.year, d.month), x)
    labels = [f'<text x="{x}" y="{top-10}" fill="{MUTED}" font-size="11">'
              f'{dt.date(y, m, 1).strftime("%b")}</text>'
              for (y, m), x in sorted(months_seen.items(), key=lambda k: k[1])]
    for r, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        labels.append(f'<text x="{left-36}" y="{top + r*(cell+gap) + 10}" fill="{MUTED}" font-size="11">{name}</text>')
    by = top + 7 * (cell + gap) + 24
    legend = [f'<text x="{W-196}" y="{by}" fill="{MUTED}" font-size="11">Less</text>']
    for i, col in enumerate(LEVELS):
        legend.append(f'<rect x="{W-160+i*17}" y="{by-11}" width="{cell}" height="{cell}" rx="3" fill="{col}"/>')
    legend.append(f'<text x="{W-70}" y="{by}" fill="{MUTED}" font-size="11">More</text>')
    total = (f'<text x="{left}" y="{by}" fill="{TEXT}" font-size="13" font-weight="700">'
             f'{st["total"]:,} contributions in the last year</text>')
    body = (prompt(24, 64, "./contributions.sh") + "\n" + "\n".join(labels + cells + legend) + total
            + f'\n{prompt(24, by + 34, "")}{cursor(24 + 9 * (len(HANDLE) + 12), by + 34)}')
    return window(W, by + 52, f"{HANDLE} — contributions.sh", body)


# ---- ascii portrait --------------------------------------------------------
RAMP = " .'`^,:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"


def ascii_portrait(cols=56) -> list[str]:
    from PIL import Image, ImageOps

    img = None
    for name in ("portrait.png", "portrait.jpg", "portrait.jpeg"):
        p = ASSETS / name
        if p.exists():
            img = Image.open(p)
            break
    if img is None:
        try:
            with urllib.request.urlopen(f"https://github.com/{USER}.png?size=240", timeout=20) as r:
                img = Image.open(io.BytesIO(r.read()))
        except Exception:
            local = ASSETS / "avatar.png"
            if not local.exists():
                return ["(add assets/portrait.png)"]
            img = Image.open(local)

    img = ImageOps.exif_transpose(img).convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("L")
    img = ImageOps.autocontrast(ImageOps.fit(img, (240, 240)))
    rows = round(cols * 0.6)  # monospace glyph is 0.6 wide; line height = font size
    img = img.resize((cols, rows))
    px = img.load()
    lines = []
    for y in range(rows):
        line = ""
        for x in range(cols):
            v = px[x, y] / 255  # 0 dark .. 1 light; dark ink drawn on a dark bg
            line += RAMP[int((1 - v) * (len(RAMP) - 1))]
        lines.append(line.rstrip())
    return lines


# ---- whoami.svg ------------------------------------------------------------
def stat_card(x, y, w, h, label, value, unit, sub) -> str:
    return f"""<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PANEL}" stroke="{BORDER}"/>
<text x="{x+12}" y="{y+20}" fill="{MUTED}" font-size="10.5">$ {escape(label)}</text>
<text x="{x+12}" y="{y+48}" font-size="24" font-weight="700" fill="{ACCENT}">{escape(str(value))}<tspan font-size="11" fill="{MUTED}" font-weight="400"> {escape(unit)}</tspan></text>
<text x="{x+12}" y="{y+66}" fill="{MUTED}" font-size="10">{escape(sub)}</text>"""


def whoami_svg(st, art) -> str:
    top = 60
    pane_h = 380
    lx, lw = 20, 420
    rx, rw = 456, W - 476

    # left pane: portrait
    fs = 9.6
    lh = fs
    art_h = len(art) * lh
    ay = top + 40 + max(0, (pane_h - 44 - art_h) / 2)
    art_w = max((len(l) for l in art), default=0) * fs * 0.6
    ax = lx + (lw - art_w) / 2
    art_svg = "\n".join(
        f'<text x="{ax:.1f}" y="{ay + i*lh:.1f}" font-size="{fs}" fill="{TEXT}" '
        f'opacity="0.92">{escape(l)}</text>'
        for i, l in enumerate(art) if l)
    left = f"""<rect x="{lx}" y="{top}" width="{lw}" height="{pane_h}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>
<text x="{lx+lw/2}" y="{top+18}" fill="{MUTED}" font-size="10" text-anchor="middle">{HANDLE}@github: ~/portrait.sh</text>
{art_svg}"""

    # right pane: stats
    cw, ch, g = (rw - 36) / 2, 76, 10
    cx1, cx2 = rx + 14, rx + 14 + cw + g
    y0 = top + 30
    cr = st["cur_range"]
    br = st["best_range"]
    bd = st["best_day"]
    cards = [
        stat_card(cx1, y0, cw, ch, "current streak", st["cur"], "days",
                  f"{fmt(cr[0])} – {fmt(cr[1])}" if cr else "start one today"),
        stat_card(cx2, y0, cw, ch, "longest streak", st["best"], "days",
                  f"{fmt(br[0])} – {fmt(br[1])}" if br else "—"),
        stat_card(cx1, y0 + ch + g, cw, ch, "contributions", f'{st["total"]:,}', "", "in the last year"),
        stat_card(cx2, y0 + ch + g, cw, ch, "active days", st["active"], f'/ {st["span"]}',
                  f'{round(100*st["active"]/st["span"])}% of the year'),
        stat_card(cx1, y0 + 2*(ch + g), cw, ch, "best day", bd[1], "", fmt(bd[0]) if bd[1] else "—"),
        stat_card(cx2, y0 + 2*(ch + g), cw, ch, "avg / active day", f'{st["avg"]:.1f}', "", "contributions"),
    ]
    # bar chart
    by = y0 + 3 * (ch + g)
    bh = top + pane_h - by - 12
    mmax = max((v for _, v in st["months"]), default=0) or 1
    bars = [f'<rect x="{cx1}" y="{by}" width="{rw-28}" height="{bh}" rx="6" fill="{PANEL}" stroke="{BORDER}"/>',
            f'<text x="{cx1+12}" y="{by+18}" fill="{MUTED}" font-size="10.5">$ contributions / month</text>']
    inner_w = rw - 52
    slot = inner_w / 12
    base = by + bh - 20
    maxh = bh - 48
    for i, (lab, v) in enumerate(st["months"]):
        h = max(2, maxh * v / mmax) if v else 2
        x = cx1 + 12 + i * slot + slot * 0.2
        col = ACCENT if v else BORDER
        bars.append(f'<rect x="{x:.1f}" y="{base-h:.1f}" width="{slot*0.6:.1f}" height="{h:.1f}" rx="2" fill="{col}"><title>{v}</title></rect>')
        bars.append(f'<text x="{x+slot*0.3:.1f}" y="{base+13}" fill="{MUTED}" font-size="9" text-anchor="middle">{lab}</text>')
    right = (f'<rect x="{rx}" y="{top}" width="{rw}" height="{pane_h}" rx="8" fill="{BG}" stroke="{BORDER}"/>'
             f'<text x="{rx+rw/2}" y="{top+18}" fill="{MUTED}" font-size="10" text-anchor="middle">{HANDLE}@github: ~/stats.sh</text>'
             + "\n".join(cards + bars))

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    foot = f'<text x="{W-20}" y="{top+pane_h+22}" fill="{MUTED}" font-size="10" text-anchor="end">last updated {stamp}</text>'
    body = prompt(24, 52, "whoami", 15) + left + right + foot
    return window(W, top + pane_h + 34, f"{HANDLE} — whoami", body)


def main():
    mock = "--mock" in sys.argv
    days = mock_days() if mock else fetch_days()
    days = [d for d in days if d[0] <= dt.date.today()]
    st = compute_stats(days)
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "contributions.svg").write_text(contributions_svg(days, st), encoding="utf-8")
    (ASSETS / "whoami.svg").write_text(whoami_svg(st, ascii_portrait()), encoding="utf-8")
    print(f"total={st['total']} active={st['active']} streak={st['cur']} longest={st['best']}")


if __name__ == "__main__":
    main()
