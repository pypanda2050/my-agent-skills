#!/usr/bin/env python3
"""
render_svg — render a .drawio (mxGraph XML) file to SVG without any draw.io binary.

This is a faithful-geometry renderer: every node/container/edge is drawn at its
exact coordinates from the XML, with fills, strokes, wrapped labels, orthogonal
edge routing (simple Manhattan approximation honoring explicit waypoints), arrow
heads, and edge labels on white chips. It intentionally covers the shape
vocabulary this skill recommends (rounded rect, rect, cylinder/database, queue,
cloud, actor, hexagon, rhombus, swimlane containers) rather than every draw.io
stencil — if you use exotic stencils, export with the draw.io CLI instead.

Usage:
    python3 render_svg.py diagram.drawio -o diagram.svg
"""

import argparse
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_tools import (  # noqa: E402
    Model, Node, parse_file, text_lines, perimeter_point, CHAR_W, LINE_H,
)

PAGE_PAD = 30


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def node_colors(n: Node):
    fill = n.style.get("fillColor", "#ffffff")
    stroke = n.style.get("strokeColor", "#000000")
    font = n.style.get("fontColor", "#000000")
    if fill == "none":
        fill = "transparent"
    return fill, stroke, font


def render_label(x, y, w, h, label, font_size, color, bold=False, valign="middle"):
    """Centered, wrapped label inside box (x,y,w,h). Returns SVG fragment."""
    if not label:
        return ""
    lines = text_lines(label, w, font_size)
    if not lines:
        return ""
    lh = font_size * LINE_H
    total = len(lines) * lh
    if valign == "top":
        start_y = y + font_size + 4
    else:
        start_y = y + (h - total) / 2 + font_size * 0.9
    weight = ' font-weight="bold"' if bold else ""
    parts = [f'<text x="{x + w / 2:.1f}" text-anchor="middle" '
             f'font-family="Helvetica,Arial,sans-serif" font-size="{font_size}" '
             f'fill="{color}"{weight}>']
    for i, line in enumerate(lines):
        parts.append(f'<tspan x="{x + w / 2:.1f}" y="{start_y + i * lh:.1f}">{esc(line)}</tspan>')
    parts.append("</text>")
    return "".join(parts)


def render_node(n: Node) -> str:
    from drawio_tools import style_shape
    fill, stroke, font = node_colors(n)
    fs = float(n.style.get("fontSize", 12) or 12)
    dash = ' stroke-dasharray="6,4"' if n.style.get("dashed") == "1" else ""
    x, y, w, h = n.x, n.y, n.w, n.h
    shape = style_shape(n.style)
    body = ""

    if "swimlane" in n.style:
        ss = n.start_size
        body += (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
                 f'fill-opacity="0.55" stroke="{stroke}" stroke-width="1.4" rx="4"{dash}/>')
        body += (f'<path d="M {x} {y + ss} H {x + w}" stroke="{stroke}" stroke-width="1"/>')
        body += render_label(x, y, w, ss, n.label, max(fs, 13), font, bold=True)
        return body

    if shape in ("cylinder3", "cylinder", "mxgraph.flowchart.database", "datastore"):
        ry = min(14.0, h * 0.18)
        body += (f'<path d="M {x} {y + ry} A {w / 2} {ry} 0 0 1 {x + w} {y + ry} '
                 f'V {y + h - ry} A {w / 2} {ry} 0 0 1 {x} {y + h - ry} Z" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash}/>')
        body += (f'<path d="M {x} {y + ry} A {w / 2} {ry} 0 0 0 {x + w} {y + ry}" '
                 f'fill="none" stroke="{stroke}" stroke-width="1.4"/>')
        body += render_label(x, y + ry, w, h - ry, n.label, fs, font)
    elif shape == "cloud" or "cloud" in shape:
        body += (f'<ellipse cx="{x + w * 0.28}" cy="{y + h * 0.55}" rx="{w * 0.26}" ry="{h * 0.34}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
                 f'<ellipse cx="{x + w * 0.52}" cy="{y + h * 0.38}" rx="{w * 0.30}" ry="{h * 0.36}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
                 f'<ellipse cx="{x + w * 0.74}" cy="{y + h * 0.56}" rx="{w * 0.24}" ry="{h * 0.32}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
                 f'<rect x="{x + w * 0.10}" y="{y + h * 0.42}" width="{w * 0.8}" height="{h * 0.35}" fill="{fill}" stroke="none"/>')
        body += render_label(x, y, w, h, n.label, fs, font)
    elif "actor" in shape or shape == "umlActor":
        cx = x + w / 2
        head_r = min(w, h) * 0.16
        body += (f'<circle cx="{cx}" cy="{y + head_r + 2}" r="{head_r}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
                 f'<path d="M {cx} {y + head_r * 2 + 2} V {y + h * 0.62} '
                 f'M {x + w * 0.12} {y + h * 0.35} H {x + w * 0.88} '
                 f'M {cx} {y + h * 0.62} L {x + w * 0.15} {y + h * 0.95} '
                 f'M {cx} {y + h * 0.62} L {x + w * 0.85} {y + h * 0.95}" '
                 f'fill="none" stroke="{stroke}" stroke-width="1.4"/>')
        body += render_label(x - 30, y + h + 2, w + 60, 16, n.label, fs, font, valign="top")
    elif "hexagon" in shape:
        k = min(20.0, w * 0.2)
        body += (f'<polygon points="{x + k},{y} {x + w - k},{y} {x + w},{y + h / 2} '
                 f'{x + w - k},{y + h} {x + k},{y + h} {x},{y + h / 2}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash}/>')
        body += render_label(x, y, w, h, n.label, fs, font)
    elif shape == "rhombus" or "rhombus" in n.style:
        body += (f'<polygon points="{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} {x},{y + h / 2}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash}/>')
        body += render_label(x + w * 0.15, y, w * 0.7, h, n.label, fs, font)
    elif "mxgraph" in shape or "queue" in shape:
        # queue-ish / unknown stencil: rect with double side lines
        body += (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="1.4" rx="3"{dash}/>'
                 f'<path d="M {x + 8} {y} V {y + h} M {x + w - 8} {y} V {y + h}" '
                 f'stroke="{stroke}" stroke-width="1"/>')
        body += render_label(x + 8, y, w - 16, h, n.label, fs, font)
    else:
        rounded = n.style.get("rounded") == "1" or shape == "rounded"
        rx = 8 if rounded else 0
        body += (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="1.4" rx="{rx}"{dash}/>')
        body += render_label(x, y, w, h, n.label, fs, font)
    return body


def orthogonal_route(model: Model, edge) -> list:
    """Manhattan route between source and target (or explicit waypoints)."""
    src = model.nodes.get(edge.source or "")
    dst = model.nodes.get(edge.target or "")
    if src is None or dst is None:
        return []
    if edge.points:
        pts = [perimeter_point(src, edge.points[0])] + edge.points + \
              [perimeter_point(dst, edge.points[-1])]
        return pts
    dx = dst.cx - src.cx
    dy = dst.cy - src.cy
    # pick dominant axis; leave/enter on facing sides, bend at midpoint
    if abs(dx) >= abs(dy):
        sxp = (src.x + src.w, src.cy) if dx >= 0 else (src.x, src.cy)
        dxp = (dst.x, dst.cy) if dx >= 0 else (dst.x + dst.w, dst.cy)
        if abs(sxp[1] - dxp[1]) < 2:
            return [sxp, dxp]
        midx = (sxp[0] + dxp[0]) / 2
        return [sxp, (midx, sxp[1]), (midx, dxp[1]), dxp]
    else:
        syp = (src.cx, src.y + src.h) if dy >= 0 else (src.cx, src.y)
        dyp = (dst.cx, dst.y) if dy >= 0 else (dst.cx, dst.y + dst.h)
        if abs(syp[0] - dyp[0]) < 2:
            return [syp, dyp]
        midy = (syp[1] + dyp[1]) / 2
        return [syp, (syp[0], midy), (dyp[0], midy), dyp]


def render_edge(model: Model, edge) -> str:
    pts = orthogonal_route(model, edge)
    if len(pts) < 2:
        return ""
    stroke = edge.style.get("strokeColor", "#555555")
    dash = ' stroke-dasharray="6,4"' if edge.style.get("dashed") == "1" else ""
    d = "M " + " L ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in pts)
    out = (f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="1.5" '
           f'marker-end="url(#arrow)"{dash}/>')
    if edge.label:
        # place label at the midpoint of the middle segment
        mid_i = (len(pts) - 1) // 2
        mx = (pts[mid_i][0] + pts[mid_i + 1][0]) / 2
        my = (pts[mid_i][1] + pts[mid_i + 1][1]) / 2
        fs = float(edge.style.get("fontSize", 11) or 11)
        tw = len(edge.label) * fs * CHAR_W + 10
        out += (f'<rect x="{mx - tw / 2:.1f}" y="{my - fs * 0.85:.1f}" width="{tw:.1f}" '
                f'height="{fs * 1.5:.1f}" fill="#ffffff" fill-opacity="0.92" rx="3"/>'
                f'<text x="{mx:.1f}" y="{my + fs * 0.32:.1f}" text-anchor="middle" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="{fs}" '
                f'fill="#444444">{esc(edge.label)}</text>')
    return out


def render(model: Model) -> str:
    x0, y0, x1, y1 = model.bounds()
    x0 -= PAGE_PAD; y0 -= PAGE_PAD; x1 += PAGE_PAD; y1 += PAGE_PAD
    w, h = x1 - x0, y1 - y0
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="{x0:.0f} {y0:.0f} {w:.0f} {h:.0f}">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#555555"/></marker></defs>',
        f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>',
    ]
    # paint containers first (outermost first), then plain nodes, then edges
    def depth(n: Node) -> int:
        d, p = 0, n.parent
        while p in model.nodes:
            d += 1
            p = model.nodes[p].parent
        return d
    containers = sorted([n for n in model.nodes.values() if n.is_container], key=depth)
    plain = [n for n in model.nodes.values() if not n.is_container and n.w > 0]
    for n in containers:
        parts.append(render_node(n))
    for n in plain:
        parts.append(render_node(n))
    for e in model.edges:
        parts.append(render_edge(model, e))
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()
    model = parse_file(args.file)
    svg = render(model)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
