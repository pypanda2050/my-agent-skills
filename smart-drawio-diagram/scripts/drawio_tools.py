#!/usr/bin/env python3
"""
drawio_tools — shared parsing/geometry library for the smart-drawio-diagram skill.

Parses .drawio (mxGraph XML) files, including deflate-compressed <diagram> content,
into a simple geometric model with ABSOLUTE coordinates, so the quality gate,
autofixer, and SVG renderer all reason about the same geometry.
"""

import base64
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- style utils

def parse_style(style: str) -> Dict[str, str]:
    """Parse a draw.io style string into a dict. Bare tokens (e.g. 'rounded',
    'swimlane', 'ellipse') are stored with value '1' under their own name."""
    out: Dict[str, str] = {}
    if not style:
        return out
    for i, token in enumerate(style.split(";")):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, _, v = token.partition("=")
            out[k.strip()] = v.strip()
        else:
            out[token] = "1"
            if i == 0:
                out["_shape"] = token  # first bare token names the base shape
    return out


def style_shape(sd: Dict[str, str]) -> str:
    """Best-effort canonical shape name from a parsed style dict."""
    if "shape" in sd:
        return sd["shape"]
    return sd.get("_shape", "rect")


# --------------------------------------------------------------------- model

@dataclass
class Node:
    id: str
    label: str = ""
    style: Dict[str, str] = field(default_factory=dict)
    x: float = 0.0          # absolute
    y: float = 0.0          # absolute
    w: float = 0.0
    h: float = 0.0
    parent: str = "1"
    is_container: bool = False
    children: List[str] = field(default_factory=list)

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def start_size(self) -> float:
        """Height of a swimlane/container title strip, 0 if none."""
        if "swimlane" in self.style:
            return float(self.style.get("startSize", 23) or 23)
        return 0.0


@dataclass
class Edge:
    id: str
    label: str = ""
    style: Dict[str, str] = field(default_factory=dict)
    source: Optional[str] = None
    target: Optional[str] = None
    points: List[Tuple[float, float]] = field(default_factory=list)  # explicit waypoints (absolute)


@dataclass
class Model:
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    page_w: float = 0.0
    page_h: float = 0.0

    def siblings(self, parent: str) -> List[Node]:
        return [n for n in self.nodes.values() if n.parent == parent]

    def top_level(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.parent in ("0", "1")]

    def bounds(self) -> Tuple[float, float, float, float]:
        if not self.nodes:
            return (0, 0, 0, 0)
        xs0 = min(n.x for n in self.nodes.values())
        ys0 = min(n.y for n in self.nodes.values())
        xs1 = max(n.x + n.w for n in self.nodes.values())
        ys1 = max(n.y + n.h for n in self.nodes.values())
        return (xs0, ys0, xs1, ys1)


# ------------------------------------------------------------------- parsing

def _maybe_decompress(diagram_text: str) -> str:
    """<diagram> bodies may be base64(raw-deflate(urlencoded xml))."""
    txt = diagram_text.strip()
    if txt.startswith("<"):
        return txt
    try:
        data = base64.b64decode(txt)
        inflated = zlib.decompress(data, -15)
        return urllib.parse.unquote(inflated.decode("utf-8"))
    except Exception:
        return txt


def load_mxgraph_root(path: str) -> ET.Element:
    """Return the <root> element of the first diagram page in a .drawio file."""
    tree = ET.parse(path)
    top = tree.getroot()
    if top.tag == "mxGraphModel":
        root = top.find("root")
    elif top.tag == "mxfile":
        diagram = top.find("diagram")
        if diagram is None:
            raise ValueError("mxfile has no <diagram> element")
        inner = list(diagram)
        if inner:  # uncompressed: <diagram><mxGraphModel>...
            model = diagram.find("mxGraphModel")
        else:      # compressed text payload
            xml_text = _maybe_decompress(diagram.text or "")
            model = ET.fromstring(xml_text)
            if model.tag != "mxGraphModel":
                model = model.find("mxGraphModel")
        if model is None:
            raise ValueError("could not locate <mxGraphModel>")
        root = model.find("root")
    else:
        raise ValueError(f"unexpected top-level tag <{top.tag}>")
    if root is None:
        raise ValueError("no <root> element found")
    return root


def _cell_of(el: ET.Element) -> Optional[ET.Element]:
    """Support both plain <mxCell> and <object label=..><mxCell>..</object> wrappers."""
    if el.tag == "mxCell":
        return el
    if el.tag in ("object", "UserObject"):
        return el.find("mxCell")
    return None


def parse_file(path: str) -> Model:
    root = load_mxgraph_root(path)
    model = Model()

    raw: Dict[str, dict] = {}
    order: List[str] = []
    duplicate_ids: List[str] = []

    for el in root:
        cell = _cell_of(el)
        if cell is None:
            continue
        cid = el.get("id") or cell.get("id")
        if cid in (None, "0", "1"):
            continue
        label = el.get("label") if el.tag in ("object", "UserObject") else cell.get("value")
        geo = cell.find("mxGeometry")
        entry = {
            "id": cid,
            "label": _strip_html(label or ""),
            "style": cell.get("style") or "",
            "vertex": cell.get("vertex") == "1",
            "edge": cell.get("edge") == "1",
            "parent": cell.get("parent") or "1",
            "source": cell.get("source"),
            "target": cell.get("target"),
            "geo": geo,
        }
        if cid in raw:
            duplicate_ids.append(cid)
        raw[cid] = entry
        order.append(cid)

    model.duplicate_ids = duplicate_ids  # type: ignore[attr-defined]

    # vertices with absolute coordinates (walk parent chain)
    def abs_xy(entry) -> Tuple[float, float]:
        geo = entry["geo"]
        x = float(geo.get("x", 0) or 0) if geo is not None else 0.0
        y = float(geo.get("y", 0) or 0) if geo is not None else 0.0
        p = entry["parent"]
        seen = set()
        while p in raw and p not in seen:
            seen.add(p)
            pe = raw[p]
            if pe["vertex"] and pe["geo"] is not None:
                x += float(pe["geo"].get("x", 0) or 0)
                y += float(pe["geo"].get("y", 0) or 0)
            p = pe["parent"]
        return x, y

    for cid in order:
        e = raw[cid]
        if not e["vertex"]:
            continue
        sd = parse_style(e["style"])
        geo = e["geo"]
        w = float(geo.get("width", 0) or 0) if geo is not None else 0.0
        h = float(geo.get("height", 0) or 0) if geo is not None else 0.0
        x, y = abs_xy(e)
        is_container = (
            "swimlane" in sd
            or sd.get("container") == "1"
            or sd.get("group") == "1"
        )
        model.nodes[cid] = Node(
            id=cid, label=e["label"], style=sd, x=x, y=y, w=w, h=h,
            parent=e["parent"], is_container=is_container,
        )

    # containers implied by having vertex children
    for n in model.nodes.values():
        if n.parent in model.nodes:
            model.nodes[n.parent].children.append(n.id)
    for n in model.nodes.values():
        if n.children:
            n.is_container = True

    # edges
    for cid in order:
        e = raw[cid]
        if not e["edge"]:
            continue
        sd = parse_style(e["style"])
        pts: List[Tuple[float, float]] = []
        geo = e["geo"]
        if geo is not None:
            arr = geo.find("Array")
            if arr is not None:
                for pt in arr.findall("mxPoint"):
                    pts.append((float(pt.get("x", 0) or 0), float(pt.get("y", 0) or 0)))
        model.edges.append(Edge(
            id=cid, label=e["label"], style=sd,
            source=e["source"], target=e["target"], points=pts,
        ))

    # edge labels stored as child vertices of edges: drop them from node checks
    edge_ids = {e.id for e in model.edges}
    model.nodes = {k: v for k, v in model.nodes.items() if v.parent not in edge_ids}

    return model


_TAG_RE = re.compile(r"<[^>]+>")

def _strip_html(text: str) -> str:
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _TAG_RE.sub("", text)
    return (
        text.replace("&lt;", "<").replace("&gt;", ">")
            .replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
            .replace("&nbsp;", " ")
    ).strip()


# ------------------------------------------------------------ text estimation

CHAR_W = 0.62  # average glyph width as a fraction of font size (Helvetica-ish)
LINE_H = 1.25  # line height as a fraction of font size


def text_lines(label: str, width: float, font_size: float) -> List[str]:
    """Estimate wrapped lines of `label` inside a box `width` px wide."""
    if not label:
        return []
    max_chars = max(1, int((width - 8) / (font_size * CHAR_W)))
    lines: List[str] = []
    for para in label.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for word in words[1:]:
            if len(cur) + 1 + len(word) <= max_chars:
                cur += " " + word
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def label_fits(node: Node) -> Tuple[bool, int]:
    """Whether the node's label plausibly fits its box. Returns (fits, n_lines)."""
    fs = float(node.style.get("fontSize", 12) or 12)
    if not node.label:
        return True, 0
    avail_h = node.h - (node.start_size if node.is_container else 0)
    if node.is_container:
        # container labels live in the title strip
        one_line_w = max(len(l) for l in node.label.split("\n")) * fs * CHAR_W
        return one_line_w <= node.w - 8, 1
    lines = text_lines(node.label, node.w, fs)
    longest = max((len(l) for l in lines), default=0)
    needed_h = len(lines) * fs * LINE_H + 8
    # a single word longer than the box can't wrap
    words = [w for l in lines for w in l.split()]
    longest_word = max((len(w) for w in words), default=0)
    word_w = longest_word * fs * CHAR_W
    fits = needed_h <= max(avail_h, node.h) and word_w <= node.w + 4
    return fits, len(lines)


# ---------------------------------------------------------------- geometry

def rects_overlap(a, b, gap: float = 0.0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 + gap <= bx0 or bx1 + gap <= ax0 or
                ay1 + gap <= by0 or by1 + gap <= ay0)


def overlap_area(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    w = min(ax1, bx1) - max(ax0, bx0)
    h = min(ay1, by1) - max(ay0, by0)
    return max(0.0, w) * max(0.0, h)


def rect_contains(outer, inner, pad: float = 0.0) -> bool:
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return ix0 >= ox0 + pad and iy0 >= oy0 + pad and ix1 <= ox1 - pad and iy1 <= oy1 - pad


def seg_intersects_rect(p1, p2, rect) -> bool:
    """Does segment p1-p2 pass through rect (strictly, not just touch edge)?"""
    x0, y0, x1, y1 = rect
    # shrink slightly so mere perimeter touches don't count
    x0 += 2; y0 += 2; x1 -= 2; y1 -= 2
    if x0 >= x1 or y0 >= y1:
        return False
    # trivial: either endpoint inside
    for (px, py) in (p1, p2):
        if x0 < px < x1 and y0 < py < y1:
            return True
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
             ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    return any(segments_cross(p1, p2, a, b) for a, b in edges)


def segments_cross(p1, p2, p3, p4) -> bool:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    return False


def perimeter_point(node: Node, toward: Tuple[float, float]) -> Tuple[float, float]:
    """Point on node's bbox perimeter along the ray from its center toward `toward`."""
    cx, cy = node.cx, node.cy
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    hw, hh = node.w / 2, node.h / 2
    scale = min(
        hw / abs(dx) if dx else float("inf"),
        hh / abs(dy) if dy else float("inf"),
    )
    return cx + dx * scale, cy + dy * scale


def edge_polyline(model: Model, edge: Edge) -> List[Tuple[float, float]]:
    """Approximate the rendered path of an edge as a polyline (absolute coords).
    Uses explicit waypoints when present, otherwise a straight center-to-center
    line clipped to the node perimeters. Orthogonal routing is approximated —
    treat results as heuristic."""
    src = model.nodes.get(edge.source or "")
    dst = model.nodes.get(edge.target or "")
    if src is None or dst is None:
        return []
    mids = list(edge.points)
    start_toward = mids[0] if mids else (dst.cx, dst.cy)
    end_toward = mids[-1] if mids else (src.cx, src.cy)
    p_start = perimeter_point(src, start_toward)
    p_end = perimeter_point(dst, end_toward)
    return [p_start] + mids + [p_end]


if __name__ == "__main__":
    m = parse_file(sys.argv[1])
    print(f"nodes={len(m.nodes)} edges={len(m.edges)} bounds={m.bounds()}")
    for n in m.nodes.values():
        kind = "container" if n.is_container else "node"
        print(f"  {kind:9s} {n.id:24s} ({n.x:.0f},{n.y:.0f} {n.w:.0f}x{n.h:.0f}) parent={n.parent} '{n.label[:40]}'")
