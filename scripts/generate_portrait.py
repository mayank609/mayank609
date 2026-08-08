#!/usr/bin/env python3
"""Turn a photo into a typing-animation ASCII portrait SVG.

Pipeline (see README.md "The photo decides everything" and "The pipeline,
and why each stage exists" for the reasoning behind each step):

  1. rembg cutout -- background forced to white so it maps to the blank
     end of the ramp instead of filling with mid-ramp noise.
  2. bilateral filter -- smooths skin while keeping edges.
  3. CLAHE (clip ~3.0) -- local contrast per tile; global autocontrast
     leaves a flatly-lit face as one tone.
  4. darkening curve -- without it the face comes out washed out; this
     is what makes glasses, brows and lips survive quantisation.
  5. map brightness to the 13-character ramp, one glyph per cell.

Output is a typing-animation SVG: each row wipes in left-to-right via a
clipPath + <animate>, staggered top to bottom, fill="freeze" so it prints
once and stops. Not a loop.

Usage:
    python3 scripts/generate_portrait.py photo.jpg --out portrait.svg
"""
import argparse
import os
import sys

import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from svgkit import RAMP, INK, BG, font_face, svg_document, escape  # noqa: E402

COLUMNS_DEFAULT = 90
CELL_W = 6.0          # px per column at CELL_W*0.6em advance == render width
ROW_ASPECT = 2.0       # monospace glyphs are ~2x taller than wide


def remove_background(img_rgb):
    from rembg import remove
    pil = Image.fromarray(img_rgb)
    cut = remove(pil)  # RGBA, subject only
    rgba = np.array(cut)
    alpha = rgba[:, :, 3:4] / 255.0
    white = np.ones_like(rgba[:, :, :3]) * 255
    composited = (rgba[:, :, :3] * alpha + white * (1 - alpha)).astype(np.uint8)
    return composited


def darkening_curve(gray):
    """Push midtones down so shadow-lit features survive the ramp.

    A plain CLAHE output stays washed out at the highlight end; this
    curve is a gamma pull on the lower half of the range plus a mild
    S-curve, tuned against the ASCII Portrait README Guide's examples.
    """
    x = gray.astype(np.float32) / 255.0
    x = np.where(x < 0.5, np.power(x, 1.6), x)
    x = np.clip((x - 0.5) * 1.15 + 0.5, 0, 1)
    return (x * 255).astype(np.uint8)


def process(path, columns=COLUMNS_DEFAULT, no_bg_removal=False):
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"could not read image: {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    if not no_bg_removal:
        rgb = remove_background(rgb)

    smoothed = cv2.bilateralFilter(rgb, d=9, sigmaColor=75, sigmaSpace=75)
    gray = cv2.cvtColor(smoothed, cv2.COLOR_RGB2GRAY)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(gray)

    darkened = darkening_curve(contrasted)

    h, w = darkened.shape
    rows = max(1, round(columns * (h / w) / ROW_ASPECT))
    small = cv2.resize(darkened, (columns, rows), interpolation=cv2.INTER_AREA)
    return small


def to_ramp_rows(brightness):
    levels = len(RAMP) - 1
    rows = []
    for row in brightness:
        chars = []
        for v in row:
            # bright pixel -> blank end of ramp (background), dark -> ink end
            level = round((255 - int(v)) / 255 * levels)
            chars.append(RAMP[level])
        # leading space clears background noise on the left edge
        rows.append(" " + "".join(chars).rstrip())
    return rows


def wipe_row(text, y, row_h, delay, dur, font_class="cell"):
    full_w = len(text) * CELL_W * 0.6 + CELL_W
    clip_id = f"row-{y}"
    cursor_x = f"{full_w:.1f}"
    return f"""<clipPath id="{clip_id}"><rect x="0" y="{y}" width="0" height="{row_h}">
<animate attributeName="width" from="0" to="{full_w:.1f}" begin="{delay:.2f}s" dur="{dur:.2f}s" fill="freeze" calcMode="spline" keySplines="0.3 0 0.2 1"/>
</rect></clipPath>
<g clip-path="url(#{clip_id})">
<text x="0" y="{y + row_h * 0.8:.1f}" class="{font_class}" xml:space="preserve">{escape(text)}</text>
<rect x="0" y="{y + row_h * 0.15:.1f}" width="{CELL_W * 0.6:.1f}" height="{row_h * 0.7:.1f}" class="cursor">
<animate attributeName="x" from="0" to="{cursor_x}" begin="{delay:.2f}s" dur="{dur:.2f}s" fill="freeze"/>
<animate attributeName="opacity" values="1;1;0" keyTimes="0;0.98;1" begin="{delay:.2f}s" dur="{dur:.2f}s" fill="freeze"/>
</rect>
</g>"""


def render_svg(rows, cell_px=460 / COLUMNS_DEFAULT):
    columns = max(len(r) for r in rows)
    font_size = cell_px / 0.6
    row_h = font_size * 1.0
    w = columns * cell_px
    h = len(rows) * row_h

    css = font_face("ramp", "jbm-r")
    css += f".cell{{font-family:'jbm-r';font-size:{font_size:.1f}px;fill:{INK};}}"
    css += f".cursor{{fill:{INK};fill-opacity:.55;}}"

    stagger = 0.06
    row_dur = 0.35
    body = "".join(
        wipe_row(row, i * row_h, row_h, i * stagger, row_dur)
        for i, row in enumerate(rows)
    )
    return svg_document(round(w), round(h), body, css, title="ASCII self-portrait, typed once")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--out", default="portrait.svg")
    ap.add_argument("--columns", type=int, default=COLUMNS_DEFAULT)
    ap.add_argument("--no-bg-removal", action="store_true", help="skip rembg (photo already has a plain background)")
    args = ap.parse_args()

    brightness = process(args.photo, columns=args.columns, no_bg_removal=args.no_bg_removal)
    rows = to_ramp_rows(brightness)
    svg = render_svg(rows)
    with open(args.out, "w") as f:
        f.write(svg)
    print(f"wrote {args.out} ({len(rows)} rows x {args.columns} cols)")


if __name__ == "__main__":
    main()
