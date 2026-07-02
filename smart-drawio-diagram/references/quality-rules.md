# Quality gate rule catalog

`quality_gate.py` exits 0 only when zero errors remain. Warnings don't block,
but a professional diagram fixes them too. `--fix` handles the mechanical ones;
everything marked "manual" needs you to edit the XML.

## Errors (block the gate)

### E-PARSE — invalid XML / duplicate ids
Cause: malformed XML, or the same `id` used twice (draw.io silently drops one).
Fix (manual): regenerate the XML; keep a set of used ids while writing.

### E-STACKED — nodes stacked on top of each other
Two siblings overlap by >30% of the smaller box. This is the classic
"LLM placed two nodes at the same coordinates" failure.
Fix: `--fix` pushes them apart, but stacking usually means a layout slot was
assigned twice — recompute that layer's x positions instead of trusting the push.

### E-OVERLAP — boxes intersect
Any positive intersection between siblings. Fix: `--fix`, or widen the layer.

### E-GAP — closer than min-gap (16px)
Boxes so close they read as touching. Fix: `--fix`, or increase H_GAP in your
layout math (60px is the recommended design gap; 16px is only the hard floor).

### E-CONTAINER-FIT — child outside container / under title strip
Causes: (a) absolute coordinates written for a container child — child coords
are RELATIVE to the container; (b) container sized before counting children;
(c) child `y < startSize + padding`.
Fix: `--fix` grows containers and nudges children clear of title strips, but if
a child sits at a wildly wrong position (cause a), recompute it as relative —
the auto-grown container would be absurdly large.

### E-EDGE-ENDPOINT — dangling edge
`source`/`target` missing or referencing a nonexistent id.
Fix (manual): point the edge at real node ids. Check for typos between the id
you wrote for the node and the one used in the edge.

### E-LABEL-CLIP — label can't fit its box
Estimated wrapped-text height exceeds the box, or one word is wider than the box.
Fix: `--fix` enlarges the node; often better manual fix: shorten the label
(≤3 words/line) and put detail on the edge label or a note instead.

## Warnings

### W-EDGE-THROUGH — edge passes through an unrelated node
Heuristic (straight/waypoint approximation of the route). Fix (manual): add a
waypoint routing around the node, pin exit/entry sides to match flow direction,
or move the node out of the corridor. Skip-layer edges should hug the diagram's
outside edge.

### W-CROSSINGS — many edge crossings
More than 6 crossing pairs (straight-line heuristic). Fix (manual): reorder
nodes within layers (barycenter pass — see layout-recipes.md), or re-assign
layers so dependencies flow one direction.

### W-ORPHAN — node with no edges
Either a forgotten connection or clutter. Connect it or delete it. (Legend/note
boxes: give them `style` containing `text;` or accept the warning.)

### W-UNLABELED-EDGE — edge without a label
An unlabeled architecture edge carries no information. Label with protocol or
payload: `HTTPS/REST`, `gRPC`, `SQL`, `events`, `sync/async`.

### W-ASPECT — drawing more elongated than 4:1
Wrap wide layers into multiple rows, or switch TB↔LR.

### W-DENSITY — nodes fill >55% of the drawing area
Increase gaps; cramped diagrams read as unprofessional even with zero overlaps.

## Thresholds

| Flag | Default | Meaning |
|---|---|---|
| `--min-gap` | 16 | hard floor for sibling whitespace (design target is 60) |
| stack ratio | 0.30 | overlap fraction that upgrades E-OVERLAP to E-STACKED |
| crossings | 6 | pairs before W-CROSSINGS fires |

## What --fix will never do

Reroute edges, change layers, reorder nodes, or touch anything structural.
That's deliberate: geometric nudging can't repair a wrong plan, and silently
restructuring your diagram would make the XML diverge from your mental model.
If `--fix` output plus one manual pass doesn't reach PASS, go back to the
layout math.
