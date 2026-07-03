---
name: smart-drawio-diagram
description: >
  Generate professional draw.io (.drawio) software architecture diagrams with an
  automated self-check / self-fix loop: a Python quality gate verifies the actual
  geometry (no overlapping or stacked shapes, children inside containers, labels
  that fit, clean edge routing), auto-fixes what it can, then exports a PNG
  headlessly (no draw.io binary required) for a final visual verification pass.
  Use this skill whenever the user asks for an architecture diagram, system
  design diagram, infrastructure/cloud diagram, microservices map, component
  diagram, data-flow diagram, network topology, or any .drawio/diagrams.net
  deliverable — especially for diagrams with many shapes, edges, and connections
  where layout quality matters. Trigger it even for vague requests like "diagram
  my system", "draw the architecture", "visualize my stack", or when the user
  complains that a previous diagram looks messy, overlapping, or unreadable.
compatibility: >
  Python 3 (stdlib only). PNG export works with zero installs on macOS
  (QuickLook) and uses the draw.io CLI, cairosvg, rsvg-convert, or inkscape when
  available. Vision-capable model recommended for the final visual check.
---

# Smart draw.io Diagram

Generate a `.drawio` architecture diagram, then **prove** it is clean instead of
hoping: a deterministic quality gate checks the real geometry, an auto-fixer
repairs mechanical problems, a headless exporter produces a PNG, and you
visually verify that PNG before delivering. Diagrams with 20–50 nodes routinely
come out of LLM generation with stacked boxes, children poking out of
containers, and edges slicing through nodes — this workflow catches all of that
before the user ever sees it.

All scripts live in this skill's `scripts/` directory (referred to as
`$SKILL/scripts` below — resolve it to this SKILL.md's real directory). They
need only the Python standard library.

## Workflow at a glance

```
Plan → Compute layout (math first!) → Write XML → Quality gate loop
     → Headless PNG export → Vision check loop → Deliver
```

Never skip the gate or the visual check "because the diagram is simple". The
cost is seconds; the failure mode it prevents (shipping an unreadable diagram)
is exactly what this skill exists to eliminate.

## Step 1 — Plan the architecture

Extract from the request:

- **Components**: services, databases, queues, caches, external APIs, users.
- **Connections**: who talks to whom, and the protocol/payload for each edge.
- **Layers**: assign every component to a tier (e.g. Clients → Edge → Services
  → Data → External). Layers become swimlane containers and drive the layout.
- **Flow direction**: top-down (TB) for layered/infra diagrams, left-right (LR)
  for data pipelines.

If the request is vague, make production-grade assumptions and state them.

## Step 2 — Compute the layout BEFORE writing XML

This is the single highest-leverage step. Do the arithmetic first; never place
nodes by eyeball. Read `references/layout-recipes.md` for the full recipes and
worked math. The core rules:

- Standard node: **160×60** (databases 140×70, actors 60×80). Consistent sizes
  read as professional; random sizes read as sloppy.
- Gaps: **≥60px horizontal** between siblings, **≥100px vertical** between
  layers (edge labels need that space to breathe).
- Containers: title strip 30px, padding 20px on all sides. Compute container
  size from its children — `w = n·160 + (n+1)·40`, `h = rows·60 + (rows+1)·30 + 30`
  — before writing any child.
- Children of a container use coordinates **relative to the container's
  top-left**, so the first child row starts at `y = 50` (30 title + 20 pad).
- Order nodes within a layer so that connected nodes sit near each other —
  this is what minimizes edge crossings.
- Edge style: `edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;` and **label
  every edge** with protocol or payload.

For XML syntax, node styles, and the color palette, read
`references/xml-format.md` before writing your first diagram in a session.

## Step 3 — Write the .drawio XML

Write the file uncompressed (`<mxfile><diagram><mxGraphModel>…`) so the tools
can inspect and fix it. Use `<object label="…">` wrappers only if you need
metadata; plain `mxCell value="…"` is fine.

## Step 4 — Quality gate loop (self-check + self-fix)

```bash
python3 $SKILL/scripts/quality_gate.py diagram.drawio --json
```

The gate parses actual geometry (absolute coordinates, container nesting) and
fails on: overlapping/stacked nodes, nodes closer than 16px, children outside
containers or under title strips, insufficient container padding, dangling
edges, labels that can't fit their boxes, edges routed through unrelated
nodes, off-center or unevenly-spaced rows of siblings, and nodes that share a
color but disagree on the rest of their styling. It warns on: short edge
labels that may crowd their arrow, labels crossed by another edge, excessive
edge crossings, orphan nodes, unlabeled edges, extreme aspect ratio, cramped
density, a missing or incomplete legend, and asymmetric top-level zone
placement. The JSON output also includes a 0-100 `score` — a supplementary
signal for whether a fix pass actually helped, not a replacement for the
PASS/FAIL error count. Full rule catalog with fix recipes:
`references/quality-rules.md`.

**On FAIL, fix in this order:**

1. Run the auto-fixer for mechanical problems:
   ```bash
   python3 $SKILL/scripts/quality_gate.py diagram.drawio --fix --json
   ```
   It separates overlapping nodes, grows containers to fit children, and
   enlarges nodes whose labels clip — then re-checks and reports what remains.
2. Fix remaining errors **by editing the XML yourself** — the auto-fixer
   deliberately won't restructure a layout, recenter a row, or reconcile
   styling. Dangling edges, dense crossing webs, off-center rows, or bad layer
   assignment mean your Step-2 plan was wrong: recompute the affected
   coordinates using the formulas in `references/layout-recipes.md` rather
   than nudging boxes one by one.
3. Re-run the gate. Repeat until `"status": "PASS"`.

If the same error survives two fix attempts, stop patching and regenerate that
region's layout from the Step-2 math — repeated local nudging usually just
moves the collision somewhere else.

Treat warnings seriously too: `W-CROSSINGS` and `W-LABEL-ARROW-OVERLAP` are
the difference between "passes" and "looks professional". Fix them when
reasonably possible (reorder nodes within a layer, add edge waypoints, widen
layer gaps).

## Step 5 — Headless PNG export

```bash
python3 $SKILL/scripts/export_png.py diagram.drawio -o diagram.png --width 1600
```

This tries the draw.io CLI first (pixel-perfect, if installed) and otherwise
renders the XML to SVG with the bundled renderer and rasterizes it (cairosvg →
rsvg-convert → inkscape → macOS QuickLook). No browser, no display, no draw.io
binary required. It always writes a companion `.svg` next to the PNG.

If it exits 3 (`"method": "svg-only"`), no rasterizer exists on this machine:
deliver the `.drawio` + `.svg`, tell the user how to export a PNG at
https://app.diagrams.net (File → Export As → PNG), and skip Step 6.

The bundled renderer covers this skill's recommended shape vocabulary. If you
used exotic draw.io stencils (mscae/AWS icon sets etc.), the SVG will show
simplified boxes — geometry and labels are still faithful, so the visual check
remains valid.

## Step 6 — Visual verification loop

Read `diagram.png` with your vision capability and check it like a reviewer
who has never seen the XML:

- Any boxes overlapping, touching, or stacked? Any text spilling out of its box
  or truncated?
- Do edges cut through unrelated boxes? Are arrowheads visible? Are labels
  legible and not sitting on top of each other?
- Is each container's title readable and are all its children clearly inside?
- Does the flow read in one dominant direction? Is whitespace balanced, or is
  one corner crowded while another is empty?

If anything fails: edit the XML (or re-run `--fix`), **re-run the quality gate**
(never export unchecked XML), re-export, re-inspect. Two to three visual
iterations is normal for a 30+ node diagram; if the same visual defect survives
three iterations, tell the user honestly instead of looping forever.

The gate checks geometry it can prove; vision catches what geometry can't
(font rendering, color contrast, overall balance). You need both.

## Step 7 — Deliver

Provide the user with:
- `diagram.drawio` — editable at https://app.diagrams.net or in draw.io desktop
- `diagram.png` (and the `.svg`)
- One line stating the verification result, e.g. "Quality gate: PASS
  (34 nodes, 41 edges, 0 errors, 2 warnings) — visually verified, no overlaps."

Honor any output directory the user specified; default to the working
directory. If they asked for other formats (PDF/JPG) and the draw.io CLI is
available, export those too (`drawio --export --format pdf …`).

## Reference files

| File | Read it when |
|---|---|
| `references/xml-format.md` | Before writing your first .drawio XML of the session — mxGraph structure, style strings, color palette |
| `references/layout-recipes.md` | At Step 2 — layered layout math, container sizing formulas, crossing-reduction, worked example |
| `references/quality-rules.md` | When the gate reports a rule you need to fix — every rule with cause and fix recipe |
| `references/house-style-source.md` | The original house style guide (QG-1 through QG-9) the gate's rules are derived from, kept verbatim for provenance |
