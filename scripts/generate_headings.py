#!/usr/bin/env python3
"""Render section-heading SVGs: the only way to put a real typeface on a
README heading, since GitHub strips <style> blocks and font-family from
inline markup. A lowercase mono label with a hairline rule running to the
right edge. Static output -- re-run by hand when a label changes, not by
the daily workflow.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from svgkit import INK, DIM, font_face, svg_document, escape  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "headings")

FONT_SIZE = 15
ADVANCE = FONT_SIZE * 0.6  # JetBrains Mono's advance width, exactly 0.600em
WIDTH = 760
HEIGHT = 34

LABELS = [
    ("about", "about"),
    ("stack", "stack"),
    ("activity", "activity"),
    ("streak", "streak"),
    ("languages", "languages"),
    ("contributions", "contributions, one square per day"),
    ("elsewhere", "elsewhere"),
]


def render(slug, label):
    text_w = len(label) * ADVANCE
    rule_x = text_w + 16

    css = font_face("heading", "jbm-h", 700)
    css += f".label{{font-family:'jbm-h';font-size:{FONT_SIZE}px;fill:{INK};letter-spacing:.02em;}}"
    css += f".rule{{stroke:{DIM};stroke-opacity:.4;stroke-width:1;}}"

    body = f'<text x="0" y="22" class="label">{escape(label)}</text>'
    body += f'<line x1="{rule_x:.1f}" y1="18" x2="{WIDTH - 4}" y2="18" class="rule"/>'
    svg = svg_document(WIDTH, HEIGHT, body, css, bg="none", title=label)
    # transparent background: this sits inline in the README's own background
    svg = svg.replace('rect.bg{fill:none;}', 'rect.bg{fill:none;}').replace(
        f'<rect class="bg" x="0" y="0" width="{WIDTH}" height="{HEIGHT}" rx="6"/>', ""
    )
    path = os.path.join(OUT_DIR, f"{slug}.svg")
    with open(path, "w") as f:
        f.write(svg)
    return path


def render_hero(name, tagline):
    width, name_size, tag_size = 520, 30, 14
    name_advance = name_size * 0.6
    text_w = len(name) * name_advance

    css = font_face("heading", "jbm-h", 700)
    css += f".name{{font-family:'jbm-h';font-size:{name_size}px;fill:{INK};letter-spacing:.01em;}}"
    css += f".tagline{{font-family:'jbm-h';font-size:{tag_size}px;fill:{DIM};}}"
    css += f".rule{{stroke:{DIM};stroke-opacity:.4;stroke-width:1;}}"

    body = f'<text x="0" y="30" class="name">{escape(name)}</text>'
    body += f'<text x="0" y="54" class="tagline">{escape(tagline)}</text>'
    body += f'<line x1="0" y1="66" x2="{min(width - 4, text_w + 40):.1f}" y2="66" class="rule"/>'
    svg = svg_document(width, 74, body, css, bg="none", title=f"{name} -- {tagline}")
    svg = svg.replace(f'<rect class="bg" x="0" y="0" width="{width}" height="74" rx="6"/>', "")
    path = os.path.join(OUT_DIR, "hero.svg")
    with open(path, "w") as f:
        f.write(svg)
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for slug, label in LABELS:
        path = render(slug, label)
        print(f"wrote {path}")
    path = render_hero("mayank bansal", "software engineer @ failproof ai -- iit jodhpur")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
