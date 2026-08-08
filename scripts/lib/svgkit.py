"""Shared helpers for building self-contained, animated SVGs.

Every generator in this repo (stats, headings, portrait) draws in the same
visual language: one ink colour, JetBrains Mono, SMIL wipe-in animation,
and a font embedded as a base64 data URI so the SVG never makes a network
request. See README.md "What GitHub actually allows" for why: GitHub
strips <style> blocks and style="" attributes from README markdown, but
an <img>-embedded SVG is rendered as an image document, so CSS inside the
SVG's own <style> tag is honoured by the browser -- it just can't reach
outside the file.
"""
import base64
import os

FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "fonts")

# 13 brightness levels, blank end first -- the shared ramp used by both
# the ASCII portrait and the year heatmap, so a "dark" cell always means
# the same thing everywhere on the page.
RAMP = " .`:-=+*cs#%@"

INK = "#c9d1d9"
DIM = "#6e7681"
BG = "#0d1117"


def _font_face_css(family, path, weight=400, style="normal"):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (
        f"@font-face{{font-family:'{family}';src:url(data:font/woff2;"
        f"base64,{b64}) format('woff2');font-weight:{weight};font-style:{style};}}"
    )


def font_face(role, family="jbm", weight=400, style="normal"):
    """role: 'ramp' | 'heading' | 'data-regular' | 'data-bold'"""
    path = os.path.join(FONTS_DIR, f"{role}.woff2")
    return _font_face_css(family, path, weight, style)


def svg_document(width, height, body, extra_css="", bg=BG, title=None):
    title_tag = f"<title>{escape(title)}</title>" if title else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">
{title_tag}<style>
{extra_css}
rect.bg{{fill:{bg};}}
</style>
<rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="6"/>
{body}
</svg>"""


def escape(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
