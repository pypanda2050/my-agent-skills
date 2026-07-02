#!/usr/bin/env python3
"""
quality_gate — deterministic lint for .drawio architecture diagrams.

Checks the diagram's actual geometry (absolute coordinates) against a set of
professional-layout rules and reports violations as JSON or human-readable text.

Exit codes:  0 = PASS (no errors; warnings allowed)
             1 = FAIL (one or more errors)
             2 = could not parse the file

Usage:
    python3 quality_gate.py diagram.drawio            # human-readable report
    python3 quality_gate.py diagram.drawio --json     # machine-readable report
    python3 quality_gate.py diagram.drawio --fix      # apply safe auto-fixes
                                                      # in place, then re-check
    python3 quality_gate.py diagram.drawio --fix --out fixed.drawio

Rules (E = error, blocks the gate; W = warning, reported only):
  E-PARSE          file is not valid drawio XML / duplicate cell ids
  E-STACKED        two sibling nodes overlap >30% of the smaller one (stacked)
  E-OVERLAP        two sibling nodes' boxes intersect at all
  E-CONTAINER-FIT  a child sticks out of its container, or sits under the
                   container's title strip
  E-EDGE-ENDPOINT  an edge is missing source and/or target
  E-LABEL-CLIP     a node's label cannot fit inside the node box
  E-GAP            two sibling nodes are closer than --min-gap (default 16px)
  W-EDGE-THROUGH   an edge's (approximate) path cuts through an unrelated node
  W-CROSSINGS      edge-edge crossings exceed threshold (heuristic, straight-
                   line approximation)
  W-ORPHAN         a non-container node has no edges at all
  W-UNLABELED-EDGE edge without a label (architecture edges should say what
                   flows over them)
  W-ASPECT         drawing is extremely elongated (>4:1)
  W-DENSITY        nodes-per-area extremely high; diagram probably cramped

Auto-fixes applied by --fix (safe, geometry-only):
  * push apart overlapping/too-close sibling nodes (iterative separation)
  * grow containers to fit their children (+padding)
  * grow node boxes so their labels fit
  * snap coordinates to a 10px grid
Structural problems (bad edge endpoints, poor layer assignment, crossing webs)
are NOT auto-fixed — regenerate the layout instead.
"""

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from itertools import combinations

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from drawio_tools import (  # noqa: E402
    Model, Node, parse_file, rects_overlap, overlap_area, rect_contains,
    seg_intersects_rect, segments_cross, edge_polyline, label_fits,
)

MIN_GAP_DEFAULT = 16.0
STACK_RATIO = 0.30
CROSSING_WARN = 6


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

    # --- sibling overlap / stacking / gap
    by_parent = {}
    for n in real_nodes.values():
        by_parent.setdefault(n.parent, []).append(n)
    for parent, sibs in by_parent.items():
        for a, b in combinations(sibs, 2):
            # container-vs-node at the same level: containment is checked
            # separately; only flag if both are plain nodes or both containers
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

    # --- containment
    for n in real_nodes.values():
        if n.parent in real_nodes:
            p = real_nodes[n.parent]
            if not rect_contains(p.bbox, n.bbox, pad=0):
                add("E-CONTAINER-FIT", "error",
                    f"'{n.label or n.id}' sticks out of container '{p.label or p.id}'",
                    [n.id, p.id])
            elif n.y < p.y + p.start_size:
                add("E-CONTAINER-FIT", "error",
                    f"'{n.label or n.id}' overlaps the title strip of container "
                    f"'{p.label or p.id}'", [n.id, p.id])

    # --- edges
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

    # --- labels
    for n in real_nodes.values():
        fits, _ = label_fits(n)
        if not fits:
            add("E-LABEL-CLIP", "error",
                f"label of '{n.label[:30]}…' does not fit its {n.w:.0f}x{n.h:.0f} box "
                f"— enlarge the node or shorten the label", [n.id])

    # --- edge through unrelated node (heuristic)
    polylines = {}
    for e in model.edges:
        pl = edge_polyline(model, e)
        if len(pl) >= 2:
            polylines[e.id] = (e, pl)
    for eid, (e, pl) in polylines.items():
        endpoints = {e.source, e.target}
        # also exempt containers of the endpoints (edges legitimately exit them)
        exempt = set(endpoints)
        for nid in list(endpoints):
            n = model.nodes.get(nid)
            while n and n.parent in model.nodes:
                exempt.add(n.parent)
                n = model.nodes[n.parent]
        for n in real_nodes.values():
            if n.id in exempt or n.is_container:
                continue
            for p1, p2 in zip(pl, pl[1:]):
                if seg_intersects_rect(p1, p2, n.bbox):
                    add("W-EDGE-THROUGH", "warning",
                        f"edge {model.nodes[e.source].label or e.source} → "
                        f"{model.nodes[e.target].label or e.target} likely passes "
                        f"through '{n.label or n.id}' — reroute or move the node",
                        [e.id, n.id])
                    break

    # --- edge crossings (straight-line heuristic)
    crossings = 0
    items = list(polylines.values())
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
        if not n.is_container and n.id not in connected and model.edges:
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
        plain = [n for n in real_nodes.values() if not n.is_container]
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

    from drawio_tools import text_lines, CHAR_W, LINE_H
    # separate to min_gap + slack so the final 10px grid snap (±5 per node)
    # cannot drop a gap back under min_gap
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

    # final polish: snap to 10px grid
    for n in model.nodes.values():
        if n.id not in cells:
            continue
        g = geo_of(n.id)
        if g is None:
            continue
        x = float(g.get("x", 0) or 0)
        y = float(g.get("y", 0) or 0)
        sx, sy = round(x / 10) * 10, round(y / 10) * 10
        if sx != x or sy != y:
            set_xywh(n.id, x=sx, y=sy)
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

    if args.json:
        print(json.dumps({
            "status": status,
            "file": target,
            "nodes": len(model.nodes),
            "edges": len(model.edges),
            "errors": errors,
            "warnings": warnings,
            "fixes_applied": fix_notes,
        }, indent=2))
    else:
        print(f"{status}: {len(model.nodes)} nodes, {len(model.edges)} edges — "
              f"{len(errors)} error(s), {len(warnings)} warning(s)")
        for note in fix_notes:
            print(f"  fixed   : {note}")
        for f in errors:
            print(f"  ERROR   [{f['rule']}] {f['message']}")
        for f in warnings:
            print(f"  warning [{f['rule']}] {f['message']}")

    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
