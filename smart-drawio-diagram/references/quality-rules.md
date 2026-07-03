# Quality gate rule catalog

`quality_gate.py` exits 0 only when zero errors remain. Warnings don't block,
but a professional diagram fixes them too. `--fix` handles the mechanical ones;
everything marked "manual" needs you to edit the XML or recompute layout math.

Every rule below also reports a 0-100 **quality score** (see bottom of this
file) so you can tell whether a fix pass actually made things better, not just
whether it happened to clear the error bar.

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

### E-CONTAINER-PADDING — container padding below the minimum
A container's tightest child clearance is under 15px on the sides/bottom, or
under 20px below the title strip. (Skipped for a container that already has an
E-CONTAINER-FIT error, so one root problem isn't counted twice.)
Fix (manual): move children inward, or grow the container — see the sizing
formulas in `layout-recipes.md`.

### E-NOT-CENTERED — a container's row of children isn't centered
Cluster the container's children into horizontal rows (by y-overlap); each
row's bounding box should be centered on the container's own center-x within
~4px. This only fires as an error for **container children** — the top-level
zones themselves get the warning-level `W-NOT-CENTERED` instead, because a
centered main spine with legitimately off-spine side zones (Monitoring,
External Services) is a common, valid pattern, not a defect.
Fix (manual): recompute `x` using the QG-1 centering formula in
`layout-recipes.md` — `start_x = parent_x + (parent_width - total_width) / 2`.

### E-UNEVEN-SPACING / E-UNEVEN-ROW-SPACING — inconsistent gaps
Within one row, the horizontal gaps between adjacent children must all be
equal (needs ≥3 children to be checkable). Across the rows of one container,
the vertical gaps between rows must also all be equal (needs ≥3 rows).
Fix (manual): pick one gap value for the group and space every item by exactly
that amount — see the arithmetic-progression recipe in `layout-recipes.md`.

### E-INCONSISTENT-STYLE — same color, different styling
Nodes sharing a `fillColor` are read by a viewer as the same category, so they
must also agree on `strokeColor`, `fontColor`, `fontSize`, `strokeWidth`, and
`rounded`. Checked separately for plain nodes and for containers/zones.
Fix (manual): copy the majority style onto the deviating node(s) — this is
usually an accidental one-off variation, not an intentional choice.

### E-EDGE-THROUGH — edge passes through an unrelated node
Traces each edge's actual routed path (the same orthogonal route
`render_svg.py` draws) and checks it against every node's bounding box. The
most common real layout defect, per the house style guide — kept as an error.
Fix (manual): add a waypoint routing around the node, pin exit/entry sides to
match flow direction, or move the node out of the corridor. Skip-layer edges
should hug the diagram's outside edge.

## Warnings

### W-LABEL-ARROW-OVERLAP — a label is crossed by another edge's line
Heuristic: both the label's position and every edge's route are estimates of
what the real renderer will draw, so this stays a warning rather than an
error — testing found it firing fairly often in busy hub areas (many edges
converging on one node) of diagrams that were visually confirmed clean.
Treat it as "worth a look," not "must fix."
Fix (manual): nudge the label along the edge (`lineTValue`, 0-1) or reroute
one of the crossing edges.

### W-EDGE-TOO-SHORT — arrow too short for its label
The routed segment a label sits on should be at least 60px (labels ≤5 chars),
120px (6-15 chars), or 180px (16+ chars) long. Also heuristic-estimated, and
common in intentionally tight, still-readable layouts — kept as a warning.
Fix (manual): increase the gap between the two connected nodes, or add a
waypoint to give the label segment more room.

### W-NOT-CENTERED / W-UNEVEN-SPACING / W-UNEVEN-ROW-SPACING — top-level version
Same checks as the E- versions above, but applied to the top-level zones
among themselves, or to any free-floating top-level nodes not inside any
zone. Kept as warnings (not errors) because asymmetric side zones and
non-grid layouts (hub-and-spoke, radial — see Recipe C in
`layout-recipes.md`) are legitimate at the top level.

### W-CROSSINGS — many edge crossings
More than 6 crossing pairs (straight-line heuristic over the routed paths).
Fix (manual): reorder nodes within layers (barycenter pass — see
`layout-recipes.md`), or re-assign layers so dependencies flow one direction.

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

### W-FLAT-ZONE — background rectangle used instead of a real container
A big, lightly-filled rectangle has real nodes placed on top of it as flat
siblings (no formal swimlane nesting). Common and visually fine — draw.io
renders it correctly — but the group can't be dragged/resized as a unit.
Consider a real `swimlane` container instead.

### W-PADDING-INCONSISTENT — container padding varies across the diagram
One or more containers' padding differs noticeably (>12px) from the median
across the diagram. Fix (manual): use one consistent padding value everywhere.

### W-LEGEND-MISSING / W-LEGEND-MISSING-ENTRY — legend accuracy (heuristic)
If the diagram uses more than one node color/category, it should have a
container labeled "Legend" whose entries' colors (fill for shape swatches,
font color for text-style lines) cover every color used elsewhere. This is
inherently fuzzy — legend conventions vary — so it's a warning, not an error.

## Thresholds

| Constant | Value | Meaning |
|---|---|---|
| `--min-gap` | 16px | hard floor for sibling whitespace (design target is 60px) |
| stack ratio | 0.30 | overlap fraction that upgrades E-OVERLAP to E-STACKED |
| crossing warn | 6 | pairs before W-CROSSINGS fires |
| center tolerance | 4px | row-centering slack (exact XML coords, so kept tight) |
| spacing tolerance | 5px | gap-evenness slack |
| min padding | 15px sides/bottom, 20px top (under a title strip) | |
| padding consistency | 12px | cross-container padding variance before warning |

These were calibrated empirically, not just against the style guide's stated
numbers: an initial pass using the guide's literal 25-30px top-padding
suggestion, and treating top-level zone alignment as an error, produced false
positives on two independently-generated, visually clean reference diagrams
(every container flagged for 20px top padding; a legitimate side zone like
"Monitoring" flagged for not aligning with the main spine). The thresholds
above are the corrected, tested values.

## Quality score (0-100)

Every finding costs points — errors more than warnings, with a few rules
weighted individually (e.g. E-PARSE at 25, since an unparseable file makes
everything else moot; W-FLAT-ZONE at 1, since it's purely stylistic). The
score floors at 0. It's a supplementary signal for the self-fix loop and for
tracking whether an edit made a diagram better, not just whether it happens to
have zero errors — PASS/FAIL (errors only) remains the authoritative gate for
whether a diagram ships. See `WEIGHTS` in `quality_gate.py` for exact values.

## What --fix will never do

Reroute edges, reorder nodes, recenter/re-space a row, reconcile inconsistent
styling, or write a legend. That's deliberate: geometric nudging can fix
mechanical overlap/containment/label-fit problems, but it can't repair a wrong
layout plan or a styling slip — and silently restructuring your diagram would
make the XML diverge from your mental model. If `--fix` output plus one manual
pass doesn't reach PASS, go back to the layout math in `layout-recipes.md`.
