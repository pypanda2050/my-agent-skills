#!/usr/bin/env python3
"""
quality_gate — deterministic lint for .drawio architecture diagrams.

Checks the diagram's actual geometry (absolute coordinates) against a set of
professional-layout rules and reports violations as JSON or human-readable text,
plus a 0-100 quality score.

Exit codes:  0 = PASS (no errors; warnings allowed)
             1 = FAIL (one or more errors)
             2 = could not parse the file

Usage:
    python3 quality_gate.py diagram.drawio            # human-readable report
    python3 quality_gate.py diagram.drawio --json     # machine-readable report
    python3 quality_gate.py diagram.drawio --fix      # apply safe auto-fixes
                                                      # in place, then re-check
    python3 quality_gate.py diagram.drawio --fix --out fixed.drawio

Rules (E = error, blocks the gate; W = warning, reported only). Each maps to a
QG-n rule from the house style guide this gate implements:
  E-PARSE               file is not valid drawio XML / duplicate cell ids
  E-STACKED             two sibling nodes overlap >30% of the smaller one
  E-OVERLAP              [QG-6] two sibling nodes' boxes intersect at all
  E-CONTAINER-FIT        a child sticks out of its container, or sits under
                         the container's title strip
  E-CONTAINER-PADDING    [QG-9] a container's padding to its children is
                         below the minimum (15px sides/bottom, 20px top)
  E-EDGE-ENDPOINT        an edge is missing source and/or target
  E-LABEL-CLIP           a node's label cannot fit inside the node box
  E-GAP                  two sibling nodes are closer than --min-gap (16px)
  E-EDGE-THROUGH         [QG-3] an edge's routed path cuts through an
                         unrelated node — the most common layout defect
  E-NOT-CENTERED         [QG-1] a container's row of children is not
                         centered in it
  E-UNEVEN-SPACING       [QG-2] horizontal gaps between siblings in a row
                         are not equal
  E-UNEVEN-ROW-SPACING   [QG-2] vertical gaps between stacked rows within a
                         container are not equal
  E-INCONSISTENT-STYLE   [QG-7] nodes sharing a fillColor (the same visual
                         category) disagree on stroke/font/rounded style
  W-LABEL-ARROW-OVERLAP  [QG-4] an edge label is crossed by another edge's
                         line (heuristic — label position and routing are
                         both estimates, so kept as a warning, not an error)
  W-EDGE-TOO-SHORT       [QG-5] the segment an edge label sits on is shorter
                         than recommended for that label's length (heuristic
                         estimate — kept as a warning, not an error)
  W-NOT-CENTERED         [QG-1] same as E-NOT-CENTERED but for the top-level
                         zones themselves, or free-floating top-level nodes —
                         kept as a warning because diagrams commonly have a
                         centered main spine plus legitimately off-spine side
                         zones (Monitoring, External Services) or non-grid
                         layouts (hub-and-spoke, radial)
  W-UNEVEN-SPACING       top-level counterpart of E-UNEVEN-SPACING
  W-UNEVEN-ROW-SPACING   top-level counterpart of E-UNEVEN-ROW-SPACING
  W-CROSSINGS            edge-edge crossings exceed threshold (heuristic)
  W-ORPHAN               a non-container node has no edges at all
  W-UNLABELED-EDGE       edge without a label
  W-ASPECT               drawing is extremely elongated (>4:1)
  W-DENSITY              nodes-per-area extremely high; diagram probably cramped
  W-FLAT-ZONE            a big lightly-filled rectangle has real nodes placed
                         on top of it as flat siblings instead of a real
                         swimlane container (visually fine, but the group
                         can't be dragged/resized as a unit)
  W-PADDING-INCONSISTENT [QG-9] containers' padding varies noticeably across
                         the diagram
  W-LEGEND-MISSING       [QG-8] diagram uses multiple colors/categories but
                         has no container labeled "Legend" (heuristic)
  W-LEGEND-MISSING-ENTRY [QG-8] a color used in the diagram has no matching
                         legend entry (heuristic)

Row-alignment (QG-1/QG-2) is checked as an ERROR for real containers' and
flat-zone groups' children — this is the skill's primary recommended layout
pattern, see references/layout-recipes.md — and as a WARNING for the
top-level zones among themselves or any leftover free-floating top-level
nodes, since asymmetric side zones and non-grid layouts are common and
legitimate at that level. Calibrated empirically: an initial, stricter pass
produced false positives on two independently-generated, visually-clean
reference diagrams (20px top padding flagged on every container; side zones
like "Monitoring" flagged for not aligning with the main spine) — the
tolerances and severities above reflect that correction.

Quality score: starts at 100, subtracts a per-rule weight for every finding
(errors weigh more than warnings), floors at 0. It's a supplementary signal
for tracking whether a fix pass actually improved the diagram — PASS/FAIL
(based on errors only) remains the authoritative gate.

Auto-fixes applied by --fix (safe, geometry-only):
  * push apart overlapping/too-close sibling nodes (iterative separation)
  * grow containers to fit their children (+padding)
  * grow node boxes so their labels fit
Structural and typographic problems (bad edge endpoints, poor layer
assignment, crossing webs, off-center rows, uneven spacing, inconsistent
styling, missing legend entries, arrows too short for their labels) are NOT
auto-fixed — regenerate the affected layout instead (see
references/layout-recipes.md and references/quality-rules.md).
"""

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from itertools import combinations

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from drawio_tools import (  # noqa: E402
    Model, Node, parse_file, rects_overlap, overlap_area, rect_contains,
    seg_intersects_rect, segments_cross, label_fits, CHAR_W,
)
from render_svg import orthogonal_route  # noqa: E402

MIN_GAP_DEFAULT = 16.0
STACK_RATIO = 0.30
CROSSING_WARN = 6
BACKDROP_CONTAIN_FRAC = 0.97   # smaller box this covered by the bigger one
BACKDROP_AREA_RATIO = 2.2      # bigger box must be at least this many times larger

# QG-1 / QG-2 — row centering and even-spacing tolerances. These are exact
# XML coordinates (not estimated), so tolerance is tight; a little slack
# still guards against float rounding.
CENTER_TOL = 4.0
SPACING_TOL = 5.0

# QG-9 — container padding. The style guide suggests 25-30px under a title
# strip; 20px is what well-laid-out reference diagrams actually use and
# reads cleanly, so that's the enforced floor (25-30 is still good guidance
# for --fix / layout-recipes.md, just not a hard gate requirement).
MIN_PAD_SIDE = 15.0
MIN_PAD_TOP_TITLE = 20.0   # containers with a title strip (real swimlanes)
MIN_PAD_BOTTOM = 15.0
PADDING_CONSISTENCY_TOL = 12.0

# QG-7 — style attributes that must match within a fillColor "category"
STYLE_ATTRS = [("strokeColor", "#000000"), ("fontColor", "#000000"),
               ("fontSize", "12"), ("strokeWidth", "1"), ("rounded", "0")]

LEGEND_RE = re.compile(r"legend", re.I)

# Score weights: how many points a finding costs. Anything not listed falls
# back to the severity default.
WEIGHTS = {
    "E-PARSE": 25, "E-EDGE-ENDPOINT": 12, "E-STACKED": 10, "E-OVERLAP": 10,
    "E-CONTAINER-FIT": 8, "E-EDGE-THROUGH": 8,
    "E-LABEL-CLIP": 6, "E-INCONSISTENT-STYLE": 5, "E-GAP": 4,
    "E-NOT-CENTERED": 4, "E-UNEVEN-SPACING": 4, "E-UNEVEN-ROW-SPACING": 4,
    "E-CONTAINER-PADDING": 4,
    "W-LABEL-ARROW-OVERLAP": 3, "W-LEGEND-MISSING": 3, "W-CROSSINGS": 3,
    "W-EDGE-TOO-SHORT": 1, "W-ORPHAN": 2, "W-ASPECT": 2, "W-DENSITY": 2,
    "W-PADDING-INCONSISTENT": 2, "W-LEGEND-MISSING-ENTRY": 2,
    "W-NOT-CENTERED": 2, "W-UNEVEN-SPACING": 2, "W-UNEVEN-ROW-SPACING": 2,
    "W-UNLABELED-EDGE": 1, "W-FLAT-ZONE": 1,
}
DEFAULT_WEIGHT = {"error": 8, "warning": 2}


def compute_score(findings) -> float:
    score = 100.0
    for f in findings:
        score -= WEIGHTS.get(f["rule"], DEFAULT_WEIGHT[f["severity"]])
    return max(0.0, round(score, 1))


def backdrop_pair(a: Node, b: Node):
    """Detect the common draw.io pattern of a large, lightly-filled rectangle
    used as a visual 'zone' backdrop, with real nodes as flat siblings placed
    on top of it (no formal swimlane/container nesting). Returns
    (backdrop_node, contained_node) if this pair matches that pattern, else
    None. This must run before overlap/stacking checks — otherwise every
    zone backdrop looks like every one of its 'children' is stacked on it."""
    area_a, area_b = a.w * a.h, b.w * b.h
    if area_a == 0 or area_b == 0:
        return None
    big, small = (a, b) if area_a >= area_b else (b, a)
    if (big.w * big.h) < BACKDROP_AREA_RATIO * (small.w * small.h):
        return None
    inter = overlap_area(a.bbox, b.bbox)
    if inter / (small.w * small.h) < BACKDROP_CONTAIN_FRAC:
        return None
    return big, small


def cluster_rows(nodes):
    """Group nodes into horizontal bands (rows) by y-overlap. Greedy single
    pass — good enough for the swimlane/grid layouts this skill recommends;
    not meant to handle arbitrary free-form scatter layouts precisely."""
    rows = []
    for n in sorted(nodes, key=lambda x: x.y):
        placed = False
        for row in rows:
            ry0 = min(x.y for x in row)
            ry1 = max(x.y + x.h for x in row)
            overlap = min(ry1, n.y + n.h) - max(ry0, n.y)
            if overlap > 0.4 * min(n.h, ry1 - ry0):
                row.append(n)
                placed = True
                break
        if not placed:
            rows.append([n])
    return rows


def check_group_alignment(add, nodes, ref_cx, severity, rule_center, rule_gap,
                          rule_row_gap, group_label):
    """QG-1 (centering) + QG-2 (even spacing) for one group of siblings."""
    rows = cluster_rows(nodes)
    if not rows:
        return
    for row in rows:
        row_sorted = sorted(row, key=lambda n: n.x)
        r0 = min(n.x for n in row_sorted)
        r1 = max(n.x + n.w for n in row_sorted)
        center = (r0 + r1) / 2
        if ref_cx is not None and abs(center - ref_cx) > CENTER_TOL:
            add(rule_center, severity,
                f"{group_label}: a row of {len(row_sorted)} item(s) "
                f"({', '.join(n.label or n.id for n in row_sorted)}) is off-center "
                f"by {abs(center - ref_cx):.0f}px", [n.id for n in row_sorted])
        if len(row_sorted) >= 3:
            gaps = [row_sorted[i + 1].x - (row_sorted[i].x + row_sorted[i].w)
                    for i in range(len(row_sorted) - 1)]
            if max(gaps) - min(gaps) > SPACING_TOL:
                add(rule_gap, severity,
                    f"{group_label}: horizontal gaps between siblings are uneven "
                    f"({', '.join(f'{g:.0f}' for g in gaps)}px) — pick one gap "
                    f"value and use it consistently", [n.id for n in row_sorted])
    if len(rows) >= 3:
        rows_by_y = sorted(rows, key=lambda r: min(n.y for n in r))
        vgaps = []
        for i in range(len(rows_by_y) - 1):
            bottom = max(n.y + n.h for n in rows_by_y[i])
            top = min(n.y for n in rows_by_y[i + 1])
            vgaps.append(top - bottom)
        if max(vgaps) - min(vgaps) > SPACING_TOL:
            add(rule_row_gap, severity,
                f"{group_label}: vertical gaps between rows are uneven "
                f"({', '.join(f'{g:.0f}' for g in vgaps)}px)", [])


def check_style_consistency(add, nodes, population_label):
    """QG-7: nodes sharing a fillColor are the same visual category and must
    agree on the rest of their styling."""
    by_fill = {}
    for n in nodes:
        fill = n.style.get("fillColor")
        if fill:
            by_fill.setdefault(fill, []).append(n)
    for fill, group in by_fill.items():
        if len(group) < 2:
            continue
        for attr, default in STYLE_ATTRS:
            values = [g.style.get(attr, default) for g in group]
            majority = Counter(values).most_common(1)[0][0]
            deviants = [(g, v) for g, v in zip(group, values) if v != majority]
            if deviants:
                names = ", ".join(f"{g.label or g.id} ({attr}={v})" for g, v in deviants)
                add("E-INCONSISTENT-STYLE", "error",
                    f"{population_label} sharing fillColor {fill} disagree on "
                    f"{attr}: {names} — rest of the group uses {attr}={majority}",
                    [g.id for g, _ in deviants])


def check_legend(add, model, real_nodes, annotation_ids, flat_zones, plain_shape_nodes):
    """QG-8 (heuristic — legend conventions vary, so this stays a warning)."""
    legend_containers = [n for n in real_nodes.values()
                         if (n.is_container or n.id in flat_zones) and LEGEND_RE.search(n.label or "")]
    used_colors = {n.style.get("fillColor") for n in plain_shape_nodes if n.style.get("fillColor")}
    if not legend_containers:
        if len(used_colors) > 1:
            add("W-LEGEND-MISSING", "warning",
                f"diagram uses {len(used_colors)} distinct node colors/categories "
                f"but has no container labeled 'Legend' — add one so viewers can "
                f"decode the colors")
        return
    documented = set()
    for lc in legend_containers:
        kids = [n for n in real_nodes.values() if n.parent == lc.id]
        kids += [model.nodes[cid] for cid in flat_zones.get(lc.id, []) if cid in model.nodes]
        for k in kids:
            if k.style.get("fillColor"):
                documented.add(k.style["fillColor"])
            if k.id in annotation_ids and k.style.get("fontColor"):
                documented.add(k.style["fontColor"])
    missing = used_colors - documented
    if missing:
        examples = [n.label or n.id for n in plain_shape_nodes
                   if n.style.get("fillColor") in missing][:4]
        add("W-LEGEND-MISSING-ENTRY", "warning",
            f"legend does not document {len(missing)} color(s) used in the "
            f"diagram (e.g. {', '.join(examples)}) — add matching legend entries")


def required_arrow_length(label: str) -> float:
    n = len(label)
    if n <= 5:
        return 60.0
    if n <= 15:
        return 120.0
    return 180.0


def label_placement(model: Model, edge):
    """Where render_svg will actually draw this edge's label: the midpoint of
    its middle routed segment. Returns None if the edge can't be routed or
    has no label. Shared by QG-4 (label-arrow overlap) and QG-5 (arrow length)
    so both checks agree with what the exported PNG actually shows."""
    if not edge.label:
        return None
    pts = orthogonal_route(model, edge)
    if len(pts) < 2:
        return None
    mid_i = (len(pts) - 1) // 2
    p1, p2 = pts[mid_i], pts[mid_i + 1]
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    fs = float(edge.style.get("fontSize", 11) or 11)
    tw = len(edge.label) * fs * CHAR_W + 10
    th = fs * 1.5
    bbox = (mx - tw / 2, my - fs * 0.85, mx + tw / 2, my - fs * 0.85 + th)
    seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    return {"bbox": bbox, "seg_len": seg_len}


# ------------------------------------------------------------------- checks

def run_checks(model: Model, min_gap: float) -> list:
    findings = []

    def add(rule, severity, message, ids=None):
        findings.append({
            "rule": rule, "severity": severity,
            "message": message, "ids": ids or [],
        })

    dup = getattr(model, "duplicate_ids", [])
    if dup:
        add("E-PARSE", "error", f"duplicate cell ids: {dup}", dup)

    real_nodes = {k: n for k, n in model.nodes.items() if n.w > 0 and n.h > 0}

    # Pure `style="text;..."` cells (titles, legend lines, captions) are
    # annotations, not architectural shapes: they have no fill/border, are
    # allowed to sit close to other things or slightly overflow their box,
    # and were never meant to have edges. Checking them like real nodes is
    # what produces false positives on diagrams that include a title or a
    # legend — a very common, legitimate pattern.
    annotation_ids = {n.id for n in real_nodes.values() if n.style.get("text") == "1"}

    # --- sibling overlap / stacking / gap (QG-6) + flat-zone detection
    by_parent = {}
    for n in real_nodes.values():
        by_parent.setdefault(n.parent, []).append(n)
    flat_zones = {}  # backdrop node id -> list of node ids placed on it
    for parent, sibs in by_parent.items():
        for a, b in combinations(sibs, 2):
            if a.id in annotation_ids or b.id in annotation_ids:
                continue
            bd = backdrop_pair(a, b)
            if bd is not None:
                backdrop, contained = bd
                flat_zones.setdefault(backdrop.id, []).append(contained.id)
                continue
            inter = overlap_area(a.bbox, b.bbox)
            if inter > 0:
                smaller = min(a.w * a.h, b.w * b.h)
                if smaller > 0 and inter / smaller >= STACK_RATIO:
                    add("E-STACKED", "error",
                        f"'{a.label or a.id}' and '{b.label or b.id}' are stacked "
                        f"on top of each other ({inter / smaller:.0%} of the smaller box)",
                        [a.id, b.id])
                else:
                    add("E-OVERLAP", "error",
                        f"'{a.label or a.id}' and '{b.label or b.id}' overlap",
                        [a.id, b.id])
            elif rects_overlap(a.bbox, b.bbox, gap=min_gap):
                add("E-GAP", "error",
                    f"'{a.label or a.id}' and '{b.label or b.id}' are closer than "
                    f"{min_gap:.0f}px", [a.id, b.id])
    for backdrop_id, child_ids in flat_zones.items():
        backdrop = model.nodes[backdrop_id]
        add("W-FLAT-ZONE", "warning",
            f"'{backdrop.label or backdrop.id}' looks like a background zone "
            f"rectangle with {len(child_ids)} node(s) placed on top as flat "
            f"siblings, not a real swimlane container — fine visually, but "
            f"consider a real container so the group can be moved/resized "
            f"together", [backdrop_id] + child_ids)

    # --- containment
    broken_containers = set()
    for n in real_nodes.values():
        if n.parent in real_nodes:
            p = real_nodes[n.parent]
            if not rect_contains(p.bbox, n.bbox, pad=0):
                add("E-CONTAINER-FIT", "error",
                    f"'{n.label or n.id}' sticks out of container '{p.label or p.id}'",
                    [n.id, p.id])
                broken_containers.add(p.id)
            elif n.y < p.y + p.start_size:
                add("E-CONTAINER-FIT", "error",
                    f"'{n.label or n.id}' overlaps the title strip of container "
                    f"'{p.label or p.id}'", [n.id, p.id])
                broken_containers.add(p.id)

    # --- container / zone padding (QG-9) — skip containers already flagged
    # for a child sticking out, so one root problem isn't double-counted.
    zone_groups = {}  # id -> (backdrop_or_container_node, [children], start_size)
    for p in real_nodes.values():
        if p.is_container:
            kids = [n for n in real_nodes.values() if n.parent == p.id]
            if kids:
                zone_groups[p.id] = (p, kids, p.start_size)
    for backdrop_id, child_ids in flat_zones.items():
        backdrop = model.nodes[backdrop_id]
        kids = [model.nodes[cid] for cid in child_ids if cid in model.nodes]
        if kids:
            zone_groups[backdrop_id] = (backdrop, kids, 0.0)

    container_paddings = {}
    for zid, (p, kids, start_size) in zone_groups.items():
        if zid in broken_containers:
            continue
        left = min(k.x - p.x for k in kids)
        right = min((p.x + p.w) - (k.x + k.w) for k in kids)
        top = min(k.y - (p.y + start_size) for k in kids)
        bottom = min((p.y + p.h) - (k.y + k.h) for k in kids)
        top_min = MIN_PAD_TOP_TITLE if start_size > 0 else MIN_PAD_SIDE
        problems = []
        if left < MIN_PAD_SIDE: problems.append(f"left {left:.0f}px")
        if right < MIN_PAD_SIDE: problems.append(f"right {right:.0f}px")
        if top < top_min: problems.append(f"top {top:.0f}px (needs {top_min:.0f}px)")
        if bottom < MIN_PAD_BOTTOM: problems.append(f"bottom {bottom:.0f}px")
        if problems:
            add("E-CONTAINER-PADDING", "error",
                f"'{p.label or p.id}' has insufficient padding: {', '.join(problems)}",
                [p.id])
        container_paddings[zid] = min(left, right, top, bottom)

    if len(container_paddings) >= 2:
        vals = sorted(container_paddings.values())
        median = vals[len(vals) // 2]
        outliers = [zid for zid, v in container_paddings.items()
                   if abs(v - median) > PADDING_CONSISTENCY_TOL]
        if outliers:
            names = [zone_groups[zid][0].label or zid for zid in outliers]
            add("W-PADDING-INCONSISTENT", "warning",
                f"container padding varies noticeably across the diagram "
                f"(outliers: {', '.join(names)}) — use one consistent padding "
                f"value everywhere", outliers)

    # --- row alignment: centering (QG-1) + even spacing (QG-2)
    for zid, (p, kids, _start_size) in zone_groups.items():
        real_kids = [k for k in kids if k.id not in annotation_ids]
        if real_kids:
            check_group_alignment(add, real_kids, p.x + p.w / 2, "error",
                                  "E-NOT-CENTERED", "E-UNEVEN-SPACING",
                                  "E-UNEVEN-ROW-SPACING",
                                  f"container '{p.label or p.id}'")

    # Zones-among-themselves is a WARNING, not an error: real diagrams commonly
    # have a centered main spine (Clients → Edge → Services → Data) plus
    # legitimately off-spine side zones (Monitoring, External Services) that
    # were never meant to align with it. Container CHILDREN alignment above
    # stays an error since that's the skill's core recommended pattern; this
    # looser top-level check is a suggestion, confirmed by testing against
    # known-good reference diagrams that legitimately place side zones off-center.
    zones_list = [g[0] for g in zone_groups.values()]
    if zones_list:
        x0, y0, x1, y1 = model.bounds()
        canvas_cx = (x0 + x1) / 2
        check_group_alignment(add, zones_list, canvas_cx, "warning",
                              "W-NOT-CENTERED", "W-UNEVEN-SPACING",
                              "W-UNEVEN-ROW-SPACING", "top-level zones")

    contained_anywhere = {k.id for g in zone_groups.values() for k in g[1]}
    toplevel_free = [n for n in real_nodes.values()
                     if n.parent in ("0", "1") and n.id not in annotation_ids
                     and n.id not in contained_anywhere and not n.is_container
                     and n.id not in flat_zones]
    if toplevel_free:
        x0, y0, x1, y1 = model.bounds()
        canvas_cx = (x0 + x1) / 2
        check_group_alignment(add, toplevel_free, canvas_cx, "warning",
                              "W-NOT-CENTERED", "W-UNEVEN-SPACING",
                              "W-UNEVEN-ROW-SPACING", "top-level layout")

    # --- style consistency per fillColor category (QG-7)
    plain_shape_nodes = [n for n in real_nodes.values()
                        if not n.is_container and n.id not in flat_zones
                        and n.id not in annotation_ids]
    check_style_consistency(add, plain_shape_nodes, "Nodes")
    container_like = [n for n in real_nodes.values()
                      if (n.is_container or n.id in flat_zones) and n.id not in annotation_ids]
    check_style_consistency(add, container_like, "Containers")

    # --- legend accuracy (QG-8, heuristic)
    check_legend(add, model, real_nodes, annotation_ids, flat_zones, plain_shape_nodes)

    # --- edges: endpoints + labels
    connected = set()
    for e in model.edges:
        if not e.source or not e.target or \
           e.source not in model.nodes or e.target not in model.nodes:
            add("E-EDGE-ENDPOINT", "error",
                f"edge '{e.label or e.id}' has a dangling endpoint "
                f"(source={e.source}, target={e.target})", [e.id])
            continue
        connected.add(e.source)
        connected.add(e.target)
        if not e.label:
            add("W-UNLABELED-EDGE", "warning",
                f"edge {model.nodes[e.source].label or e.source} → "
                f"{model.nodes[e.target].label or e.target} has no label", [e.id])

    # --- labels fit their boxes
    for n in real_nodes.values():
        if n.id in annotation_ids:
            continue
        fits, _ = label_fits(n)
        if not fits:
            add("E-LABEL-CLIP", "error",
                f"label of '{n.label[:30]}…' does not fit its {n.w:.0f}x{n.h:.0f} box "
                f"— enlarge the node or shorten the label", [n.id])

    # --- edge routing: through-node (QG-3), crossings, arrow length (QG-5),
    # label-arrow overlap (QG-4). All share one routed polyline per edge —
    # the same orthogonal Manhattan route render_svg.py actually draws, so
    # these checks agree with what the exported PNG shows.
    routes = {}
    for e in model.edges:
        if e.source in model.nodes and e.target in model.nodes:
            pts = orthogonal_route(model, e)
            if len(pts) >= 2:
                routes[e.id] = (e, pts)

    for eid, (e, pl) in routes.items():
        endpoints = {e.source, e.target}
        exempt = set(endpoints)
        for nid in list(endpoints):
            n = model.nodes.get(nid)
            while n and n.parent in model.nodes:
                exempt.add(n.parent)
                n = model.nodes[n.parent]
        for n in real_nodes.values():
            if n.id in exempt or n.is_container or n.id in flat_zones or n.id in annotation_ids:
                continue
            for p1, p2 in zip(pl, pl[1:]):
                if seg_intersects_rect(p1, p2, n.bbox):
                    add("E-EDGE-THROUGH", "error",
                        f"edge {model.nodes[e.source].label or e.source} → "
                        f"{model.nodes[e.target].label or e.target} passes through "
                        f"'{n.label or n.id}' — reroute (add a waypoint) or move the node",
                        [e.id, n.id])
                    break

    for eid, (e, pl) in routes.items():
        place = label_placement(model, e)
        if place is None:
            continue
        req = required_arrow_length(e.label)
        if place["seg_len"] < req:
            add("W-EDGE-TOO-SHORT", "warning",
                f"label '{e.label}' sits on a {place['seg_len']:.0f}px segment, "
                f"shorter than the recommended {req:.0f}px for its length — "
                f"increase spacing between the connected nodes", [e.id])
        for other_id, (e2, pl2) in routes.items():
            if other_id == eid:
                continue
            for q1, q2 in zip(pl2, pl2[1:]):
                if seg_intersects_rect(q1, q2, place["bbox"]):
                    src2 = model.nodes[e2.source].label or e2.source
                    dst2 = model.nodes[e2.target].label or e2.target
                    # Warning, not error: label position and routing are both
                    # heuristic approximations of what render_svg (and real
                    # draw.io) will draw, and testing showed this pair-wise
                    # check fires often in busy hub areas of diagrams that were
                    # visually confirmed clean — treat as a "check this" nudge.
                    add("W-LABEL-ARROW-OVERLAP", "warning",
                        f"label '{e.label}' is crossed by the edge {src2} → {dst2} "
                        f"— move the label (lineTValue) or reroute one of the edges",
                        [eid, other_id])
                    break

    # --- edge crossings (straight-line heuristic over the routed polylines)
    crossings = 0
    items = list(routes.values())
    for (e1, pl1), (e2, pl2) in combinations(items, 2):
        if {e1.source, e1.target} & {e2.source, e2.target}:
            continue  # sharing a node: touching is normal
        crossed = False
        for a1, a2 in zip(pl1, pl1[1:]):
            for b1, b2 in zip(pl2, pl2[1:]):
                if segments_cross(a1, a2, b1, b2):
                    crossed = True
                    break
            if crossed:
                break
        if crossed:
            crossings += 1
    if crossings > CROSSING_WARN:
        add("W-CROSSINGS", "warning",
            f"{crossings} edge pairs cross (heuristic) — consider reordering nodes "
            f"within layers or re-assigning layers to reduce crossings")

    # --- orphans
    for n in real_nodes.values():
        if (not n.is_container and n.id not in flat_zones and n.id not in annotation_ids
                and n.id not in connected and model.edges):
            add("W-ORPHAN", "warning",
                f"'{n.label or n.id}' has no edges — connect it or remove it", [n.id])

    # --- global shape
    x0, y0, x1, y1 = model.bounds()
    w, h = x1 - x0, y1 - y0
    if w > 0 and h > 0:
        ratio = max(w / h, h / w)
        if ratio > 4:
            add("W-ASPECT", "warning",
                f"drawing is {w:.0f}x{h:.0f} ({ratio:.1f}:1) — very elongated; "
                f"consider wrapping layers")
        plain = [n for n in real_nodes.values()
                if not n.is_container and n.id not in flat_zones and n.id not in annotation_ids]
        if plain:
            used = sum(n.w * n.h for n in plain)
            if used / (w * h) > 0.55:
                add("W-DENSITY", "warning",
                    "nodes fill >55% of the drawing area — diagram is cramped; "
                    "increase spacing")

    return findings


# ----------------------------------------------------------------- auto-fix

def autofix(path: str, out: str, min_gap: float) -> list:
    """Apply safe geometric fixes directly to the XML. Returns list of fix notes."""
    notes = []
    tree = ET.parse(path)
    top = tree.getroot()
    if top.tag == "mxGraphModel":
        root = top.find("root")
    else:
        diagram = top.find("diagram")
        model_el = diagram.find("mxGraphModel") if diagram is not None else None
        if model_el is None:
            raise SystemExit("--fix requires an uncompressed .drawio file "
                             "(re-save the XML uncompressed)")
        root = model_el.find("root")

    # index cells + geometries
    cells = {}
    for el in root:
        c = el if el.tag == "mxCell" else el.find("mxCell")
        if c is None:
            continue
        cid = el.get("id") or c.get("id")
        if cid in (None, "0", "1"):
            continue
        cells[cid] = (el, c)

    def geo_of(cid):
        el, c = cells[cid]
        return c.find("mxGeometry")

    def set_xywh(cid, x=None, y=None, w=None, h=None):
        g = geo_of(cid)
        if g is None:
            return
        if x is not None: g.set("x", f"{x:g}")
        if y is not None: g.set("y", f"{y:g}")
        if w is not None: g.set("width", f"{w:g}")
        if h is not None: g.set("height", f"{h:g}")

    def reparse():
        tree.write(out, encoding="unicode", xml_declaration=False)
        return parse_file(out)

    tree.write(out, encoding="unicode", xml_declaration=False)
    model = parse_file(out)

    from drawio_tools import text_lines, LINE_H
    # separate to min_gap + slack so rounding in later passes cannot drop a
    # gap back under min_gap
    target_gap = min_gap + 12
    PAD = 15

    def fix_labels(model):
        changed = False
        for n in list(model.nodes.values()):
            if n.id not in cells or n.is_container or not n.label:
                continue
            fits, _ = label_fits(n)
            if fits:
                continue
            fs = float(n.style.get("fontSize", 12) or 12)
            words = n.label.replace("\n", " ").split()
            longest_word_w = max((len(w) for w in words), default=0) * fs * CHAR_W + 12
            new_w = max(n.w, longest_word_w)
            lines = text_lines(n.label, new_w, fs)
            new_h = max(n.h, len(lines) * fs * LINE_H + 14)
            set_xywh(n.id, w=new_w, h=new_h)
            notes.append(f"grew '{n.label[:30]}' to {new_w:.0f}x{new_h:.0f} to fit label")
            changed = True
        return changed

    def separate_siblings(model):
        """Iteratively push apart violating sibling pairs. One pair per parent
        group per round (coords go stale after a move), reparse between rounds."""
        any_change = False
        for _round in range(120):
            moved = False
            by_parent = {}
            for n in model.nodes.values():
                if n.w > 0 and n.h > 0:
                    by_parent.setdefault(n.parent, []).append(n)
            for sibs in by_parent.values():
                for a, b in combinations(sibs, 2):
                    if not rects_overlap(a.bbox, b.bbox, gap=min_gap):
                        continue
                    need_x = (a.w + b.w) / 2 + target_gap - abs(a.cx - b.cx)
                    need_y = (a.h + b.h) / 2 + target_gap - abs(a.cy - b.cy)
                    if need_x <= 0 or need_y <= 0:
                        continue
                    ga, gb = geo_of(a.id), geo_of(b.id)
                    if ga is None or gb is None:
                        continue
                    if need_x <= need_y:  # cheaper to separate horizontally
                        push = need_x / 2 + 1
                        sign = 1 if a.cx <= b.cx else -1
                        set_xywh(a.id, x=float(ga.get("x", 0) or 0) - sign * push)
                        set_xywh(b.id, x=float(gb.get("x", 0) or 0) + sign * push)
                    else:
                        push = need_y / 2 + 1
                        sign = 1 if a.cy <= b.cy else -1
                        set_xywh(a.id, y=float(ga.get("y", 0) or 0) - sign * push)
                        set_xywh(b.id, y=float(gb.get("y", 0) or 0) + sign * push)
                    moved = True
                    notes.append(f"separated '{a.label or a.id}' / '{b.label or b.id}'")
                    break  # this group's coords are stale now
            model = reparse()
            any_change = any_change or moved
            if not moved:
                break
        return any_change, model

    def fix_containment(model):
        changed = False
        for n in list(model.nodes.values()):
            if n.parent not in model.nodes or n.id not in cells:
                continue
            p = model.nodes[n.parent]
            g = geo_of(n.id)
            if g is None:
                continue
            rel_x = float(g.get("x", 0) or 0)
            rel_y = float(g.get("y", 0) or 0)
            min_y = p.start_size + PAD
            if rel_y < min_y:
                set_xywh(n.id, y=min_y)
                notes.append(f"moved '{n.label or n.id}' below title strip of '{p.label or p.id}'")
                changed = True
            if rel_x < PAD:
                set_xywh(n.id, x=PAD)
                notes.append(f"nudged '{n.label or n.id}' inside '{p.label or p.id}'")
                changed = True
        model = reparse()
        for p in list(model.nodes.values()):
            if not p.children or p.id not in cells:
                continue
            kids = [model.nodes[c] for c in p.children if c in model.nodes]
            if not kids:
                continue
            need_w = max(k.x + k.w for k in kids) - p.x + PAD
            need_h = max(k.y + k.h for k in kids) - p.y + PAD
            if need_w > p.w or need_h > p.h:
                set_xywh(p.id, w=max(p.w, need_w), h=max(p.h, need_h))
                notes.append(f"grew container '{p.label or p.id}' to fit children")
                changed = True
        return changed, reparse()

    # fixed-point outer loop: growing a container can create a new sibling
    # overlap, whose separation can push a child near a container wall, etc.
    for _pass in range(6):
        changed = fix_labels(model)
        model = reparse() if changed else model
        sep_changed, model = separate_siblings(model)
        cont_changed, model = fix_containment(model)
        if not (changed or sep_changed or cont_changed):
            break

    tree.write(out, encoding="unicode", xml_declaration=False)
    return notes


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="draw.io diagram quality gate")
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--fix", action="store_true", help="apply safe auto-fixes first")
    ap.add_argument("--out", help="with --fix: write fixed file here (default: in place)")
    ap.add_argument("--min-gap", type=float, default=MIN_GAP_DEFAULT,
                    help=f"minimum whitespace between sibling nodes (default {MIN_GAP_DEFAULT:g}px)")
    args = ap.parse_args()

    fix_notes = []
    target = args.file
    if args.fix:
        target = args.out or args.file
        try:
            fix_notes = autofix(args.file, target, args.min_gap)
        except SystemExit:
            raise
        except Exception as exc:
            print(json.dumps({"status": "parse-error", "error": str(exc)}) if args.json
                  else f"PARSE ERROR during --fix: {exc}")
            sys.exit(2)

    try:
        model = parse_file(target)
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "parse-error", "error": str(exc)}))
        else:
            print(f"PARSE ERROR: {exc}")
        sys.exit(2)

    findings = run_checks(model, args.min_gap)
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    status = "PASS" if not errors else "FAIL"
    score = compute_score(findings)

    if args.json:
        print(json.dumps({
            "status": status,
            "score": score,
            "file": target,
            "nodes": len(model.nodes),
            "edges": len(model.edges),
            "errors": errors,
            "warnings": warnings,
            "fixes_applied": fix_notes,
        }, indent=2))
    else:
        print(f"{status} (score {score:.0f}/100): {len(model.nodes)} nodes, "
              f"{len(model.edges)} edges — {len(errors)} error(s), {len(warnings)} warning(s)")
        for note in fix_notes:
            print(f"  fixed   : {note}")
        for f in errors:
            print(f"  ERROR   [{f['rule']}] {f['message']}")
        for f in warnings:
            print(f"  warning [{f['rule']}] {f['message']}")

    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
