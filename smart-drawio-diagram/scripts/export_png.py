#!/usr/bin/env python3
"""
export_png — headless .drawio → PNG export with automatic fallback chain.

Order of preference (first available wins):
  1. draw.io desktop CLI      — pixel-perfect official rendering
  2. render_svg.py + rasterizer:
       a. cairosvg (python)
       b. rsvg-convert
       c. inkscape
       d. qlmanage (macOS QuickLook — always present on macOS, no install)

Always also writes a companion .svg next to the PNG (from render_svg.py) so
there is a scalable artifact even when rasterization succeeds.

Usage:
    python3 export_png.py diagram.drawio -o diagram.png [--width 1600]

Prints JSON: {"png": path-or-null, "svg": path, "method": "..."}
Exit 0 if a PNG was produced, 3 if only SVG could be produced.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DRAWIO_CANDIDATES = [
    "drawio", "draw.io",
    "/Applications/draw.io.app/Contents/MacOS/draw.io",
    "C:\\Program Files\\draw.io\\draw.io.exe",
]


def find_drawio():
    for cand in DRAWIO_CANDIDATES:
        path = shutil.which(cand) or (cand if os.path.exists(cand) else None)
        if path:
            try:
                r = subprocess.run([path, "--version"], capture_output=True,
                                   timeout=20)
                if r.returncode == 0 and (r.stdout or r.stderr):
                    return path
            except Exception:
                continue
    return None


def export_with_drawio(cli, src, png, width):
    cmd = [cli, "--export", "--format", "png", "--width", str(width),
           "--output", png, src]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return r.returncode == 0 and os.path.exists(png) and os.path.getsize(png) > 0


def make_svg(src, svg_path):
    from drawio_tools import parse_file
    from render_svg import render
    model = parse_file(src)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(render(model))


def rasterize(svg_path, png_path, width):
    # a) cairosvg
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=width)
        return "cairosvg"
    except Exception:
        pass
    # b) rsvg-convert
    if shutil.which("rsvg-convert"):
        r = subprocess.run(["rsvg-convert", "-w", str(width), svg_path,
                            "-o", png_path], capture_output=True)
        if r.returncode == 0 and os.path.exists(png_path):
            return "rsvg-convert"
    # c) inkscape
    if shutil.which("inkscape"):
        r = subprocess.run(["inkscape", svg_path, "--export-type=png",
                            f"--export-filename={png_path}",
                            f"--export-width={width}"], capture_output=True)
        if r.returncode == 0 and os.path.exists(png_path):
            return "inkscape"
    # d) qlmanage (macOS QuickLook) — thumbnails SVG via WebKit, no installs.
    # QuickLook produces SQUARE thumbnails scaled to FILL (cropping the longer
    # side), so feed it a square-padded copy of the SVG: content stays centered
    # and complete, with harmless white margins.
    if sys.platform == "darwin" and shutil.which("qlmanage"):
        import re
        with open(svg_path, encoding="utf-8") as f:
            svg = f.read()
        m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
        sq_path = svg_path + ".square.svg"
        if m:
            x0, y0, w, h = map(float, m.groups())
            side = max(w, h)
            nx0 = x0 - (side - w) / 2
            ny0 = y0 - (side - h) / 2
            sq = svg.replace(
                m.group(0), f'viewBox="{nx0:.0f} {ny0:.0f} {side:.0f} {side:.0f}"')
            sq = re.sub(r'width="[\d.]+" height="[\d.]+"',
                        f'width="{side:.0f}" height="{side:.0f}"', sq, count=1)
            # extend the white background to the padded canvas
            sq = sq.replace(">\n<defs", f'>\n<rect x="{nx0:.0f}" y="{ny0:.0f}" '
                            f'width="{side:.0f}" height="{side:.0f}" fill="#ffffff"/>\n<defs',
                            1)
            with open(sq_path, "w", encoding="utf-8") as f:
                f.write(sq)
        else:
            shutil.copy(svg_path, sq_path)
        outdir = os.path.dirname(os.path.abspath(png_path)) or "."
        try:
            subprocess.run(["qlmanage", "-t", "-s", str(width), "-o", outdir,
                            sq_path], capture_output=True, timeout=60)
        finally:
            thumb = os.path.join(outdir, os.path.basename(sq_path) + ".png")
        if os.path.exists(sq_path):
            os.remove(sq_path)
        if os.path.exists(thumb) and os.path.getsize(thumb) > 0:
            if os.path.abspath(thumb) != os.path.abspath(png_path):
                shutil.move(thumb, png_path)
            return "qlmanage"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("-o", "--output", required=True, help="PNG output path")
    ap.add_argument("--width", type=int, default=1600,
                    help="PNG pixel width (default 1600)")
    ap.add_argument("--no-drawio-cli", action="store_true",
                    help="skip the draw.io CLI even if installed")
    args = ap.parse_args()

    png = args.output
    svg = os.path.splitext(png)[0] + ".svg"

    # always produce the SVG companion (also serves as rasterizer input)
    try:
        make_svg(args.file, svg)
    except Exception as exc:
        print(json.dumps({"png": None, "svg": None, "method": None,
                          "error": f"SVG render failed: {exc}"}))
        sys.exit(3)

    method = None
    if not args.no_drawio_cli:
        cli = find_drawio()
        if cli:
            try:
                if export_with_drawio(cli, args.file, png, args.width):
                    method = "drawio-cli"
            except Exception:
                method = None

    if method is None:
        method = rasterize(svg, png, args.width)

    if method:
        print(json.dumps({"png": os.path.abspath(png),
                          "svg": os.path.abspath(svg), "method": method}))
        sys.exit(0)
    else:
        print(json.dumps({"png": None, "svg": os.path.abspath(svg),
                          "method": "svg-only",
                          "note": "no rasterizer available; deliver the SVG and "
                                  ".drawio, and skip the PNG vision check"}))
        sys.exit(3)


if __name__ == "__main__":
    main()
