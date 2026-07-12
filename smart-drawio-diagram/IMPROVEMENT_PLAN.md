# smart-drawio-diagram — Improvement Plan

Date: 2026-07-12
Scope: plan only — no implementation in this document.
Skill under change: `~/.claude/skills/smart-drawio-diagram`

## Goals

1. **Template look-and-feel matching** — given a template diagram supplied by the
   user as a `.drawio`, `.svg`, or `.png` file, generate new diagrams that match
   its visual style (palette, shapes, fonts, edge conventions, container
   treatment, spacing rhythm), not the skill's hard-coded house palette.
2. **Maximize the quality-gate score** — layouts should not merely PASS (zero
   errors) but reliably reach the highest achievable 0-100 score by also
   eliminating the warning-class findings that currently cost points
   (`W-CROSSINGS`, `W-LEGEND-*`, `W-LABEL-ARROW-OVERLAP`, `W-UNLABELED-EDGE`,
   spacing/centering warnings at top level, etc.).

## Where the skill stands today (baseline)

- The gate (`scripts/quality_gate.py`, 860 lines) checks 27 rules, computes a
  weighted 0-100 score, and auto-fixes only three mechanical problems
  (separate overlaps, grow containers, grow clipped labels). Everything else —
  recentering, spacing equalization, style reconciliation, edge rerouting,
  legends — is left to the agent to hand-edit.
- Style is prescribed, not learned: one fixed palette and shape vocabulary in
  `references/xml-format.md`. There is no mechanism to ingest a user's template
  in any format. (`compare-drawio-diagram-skill.md` already flagged this as gap
  #4 vs. Agents365-ai's learn/apply style-preset system.)
- Layout is computed by the agent following prose recipes
  (`references/layout-recipes.md`); the barycenter crossing-reduction pass is
  described but not runnable code. Iteration-1 evals PASS with 0 errors, but
  the without-skill runs show 7–13 warnings slipping through — the same class
  of findings that would cap the score below 100 on harder inputs.
- The score is reported as a single number; `--json` doesn't say which findings
  cost how many points, so an agent can't prioritize the most expensive fix.

## Part A — Template look-and-feel matching

### A1. Define a style-profile format (the contract everything else uses)

New file `references/style-profile-schema.md` + JSON schema. A profile captures,
per visual role (client / service / datastore / queue / external / infra /
alert / container / legend):

- `fillColor`, `strokeColor`, `fontColor`, `strokeWidth`
- shape (`rounded` + `arcSize`, cylinder, actor, rhombus, custom stencil name)
- node dimensions (median w×h observed per role)
- fonts: family, node/container/edge label sizes, bold usage
- edge conventions: `edgeStyle`, stroke color, arrowhead, dashed-for-async
  yes/no, label font size, label placement habit
- container conventions: swimlane vs. flat backdrop, `startSize`, title
  styling, fill lightness relative to member nodes
- spacing rhythm: median sibling H-gap, layer V-gap, container padding
- background / page: grid on/off, page size, shadow
- `provenance`: source file, extraction method (`drawio-parse` | `svg-parse` |
  `vision`), and a per-field `confidence` (high for parsed XML, lower for
  vision) — mirrors recommendation #6 from the comparison research.

Profiles are stored as named JSON files in `$SKILL/styles/<name>.json` (plus a
`default.json` that reproduces today's house palette so existing behavior is
unchanged when no template is given).

### A2. New script `scripts/extract_style.py` — one extractor, three input tiers

```
python3 $SKILL/scripts/extract_style.py template.drawio -o profile.json
python3 $SKILL/scripts/extract_style.py template.svg    -o profile.json
python3 $SKILL/scripts/extract_style.py template.png    -o profile.json   # partial; see below
```

- **`.drawio` (highest fidelity, fully deterministic).** Reuse
  `drawio_tools.parse_file`. Cluster nodes by `fillColor` (the gate already
  treats fill as the category key for E-INCONSISTENT-STYLE — same convention),
  take per-cluster modal style attributes, measure real gaps/padding from
  geometry, read edge styles from edge cells. Confidence: high on every field.
- **`.svg` (deterministic, slightly lossy).** Parse the SVG XML with
  `xml.etree`: collect `fill`/`stroke`/`stroke-width` from `rect`/`path`/
  `ellipse`, corner rounding from `rx`, fonts from `text`/`style` attrs,
  spacing from element bounding boxes. draw.io-exported SVGs keep a regular
  structure, which this tier should explicitly support; foreign SVGs degrade
  gracefully to palette + fonts only. Confidence: high for colors/fonts,
  medium for role assignment and spacing.
- **`.png` (vision-assisted, stdlib-assisted).** Two cooperating halves:
  1. A small stdlib-only pixel pass (PNG is decodable with `zlib` + `struct`;
     no Pillow dependency, keeping the skill's zero-install guarantee) that
     builds a color histogram and returns the dominant fill/stroke/background
     candidates as exact hex values — vision models are unreliable at exact
     hex; the histogram makes colors exact.
  2. A guided vision checklist (new `references/template-extraction.md`) the
     agent walks while looking at the PNG: which shapes are used for which
     roles, rounded or square corners, edge style (orthogonal/straight/curved),
     dashed conventions, label casing, container treatment, legend presence.
     The agent merges its answers with the histogram into the profile JSON,
     marking vision-derived fields `confidence: medium/low`.
- All three tiers emit the same schema, so downstream steps don't care which
  format the template arrived in.

### A3. Apply the profile at generation time

- `references/xml-format.md` gets a short refactor: the "Color palette" and
  "Node style catalog" tables become the **default profile**, and the doc gains
  a section "Generating against a style profile" that maps each profile field
  to the style-string fragment to emit.
- SKILL.md workflow gains a **Step 1b — Ingest template (if the user supplied
  one)**: run `extract_style.py`, review low-confidence fields against the
  template image, save the profile, and use it for every subsequent style
  decision. Also document `--style <name>` reuse ("make it look like our
  standard template" across sessions) — list/save/set-default is a thin file
  convention, not a new subsystem.

### A4. Verify conformance, don't hope — gate + renderer + vision

- `quality_gate.py --style profile.json` adds a **style-conformance rule
  family** (score-affecting like all others):
  - `E-STYLE-OFFPALETTE` — a node/edge uses a fill/stroke not in the profile
    (exact match, small tolerance for draw.io's own normalization)
  - `E-STYLE-ROLE-MISMATCH` — nodes in one fill-category deviate from the
    profile's shape/font/stroke for that role (generalizes today's
    E-INCONSISTENT-STYLE from "internally consistent" to "consistent with the
    template")
  - `W-STYLE-SPACING-DRIFT` — measured gaps/padding deviate >25% from the
    profile's spacing rhythm
  - `W-STYLE-FONT-DRIFT` — font sizes/family differ from profile
  - Without `--style`, behavior is exactly today's (checked against
    `styles/default.json` semantics) — no regression for non-template use.
- `render_svg.py`: honor profile fields it currently hard-codes (font family,
  stroke widths, arrowhead style, dashed patterns, container title styling) so
  the headless PNG preview is faithful to the template, not just to the house
  style. This protects the skill's core "the preview is truthful" promise.
- **Vision step 6 extension**: when a template exists, render template and
  output side by side (or read both images) and run a look-and-feel checklist:
  same palette temperature, same corner language, same edge feel, same label
  density. This catches gestalt mismatches geometry can't express.

### A5. Out of scope for this iteration (explicitly)

- Learning from hand-drawn/whiteboard photos (only clean PNG exports).
- Pixel-perfect replication of exotic vendor stencils in the fallback renderer
  (tracked separately as comparison-doc recommendation #2); a template that
  uses `mxgraph.aws4.*` shapes gets its **colors/fonts/spacing** matched, with
  the stencil names carried into the `.drawio` so draw.io itself renders them.

## Part B — Satisfy the gate and maximize the score

### B1. Make the score actionable

- `quality_gate.py --json` output adds per-finding `points` (the weight
  actually subtracted) and a `score_breakdown` summary (points lost per rule).
  Agents then fix the most expensive findings first instead of in list order.
- Add `--target-score N` (default 100): exit code stays error-driven (PASS/FAIL
  semantics unchanged), but the JSON gains `"target_met": bool` so the loop in
  SKILL.md has a crisp termination test.

### B2. Runnable layout engine — correct by construction, then verified

New `scripts/layout_engine.py` (stdlib only), implementing what
`layout-recipes.md` currently asks the agent to do by hand:

- Input: a small JSON spec (nodes with role + layer hints, edges with labels,
  requested direction TB/LR) — the Step-1 plan, formalized.
- Longest-path layer assignment → barycenter ordering (one down sweep + one up
  sweep, exactly the documented heuristic) → coordinate assignment using the
  recipe constants (or the style profile's spacing rhythm when one is active)
  → container sizing from contents → emits ready-to-gate `.drawio` XML,
  including pinned exit/entry ports and outside-lane waypoints for skip-layer
  edges (the current top source of `E-EDGE-THROUGH` / `W-CROSSINGS`).
- The agent may still hand-write XML for small diagrams; SKILL.md recommends
  the engine at ≥ ~15 nodes. The gate remains the authority either way —
  verify-after-layout stays, per the comparison doc's recommendation #3.
- Expected effect: first-pass scores move from "PASS with several warnings" to
  "PASS, 95+", and fix-loop iterations drop on dense diagrams.

### B3. Extend the auto-fixer to cover the mechanical remainder

Today `--fix` handles 3 of 13 error rules. Add deterministic fixes for the
rules that are arithmetic, not judgment:

| Rule | Auto-fix |
|---|---|
| `E-NOT-CENTERED` | recompute row x-offsets to center in container |
| `E-UNEVEN-SPACING` / `E-UNEVEN-ROW-SPACING` | redistribute siblings/rows evenly |
| `E-CONTAINER-PADDING` | shift children / grow container to the floor values |
| `E-INCONSISTENT-STYLE` | reconcile stragglers to the category's modal style (or the profile's role style when `--style` is active) |
| `E-EDGE-THROUGH` | insert a perimeter waypoint around the offending node (reuse `render_svg.orthogonal_route` to validate the new path before writing it) |
| `W-LEGEND-MISSING` / `W-LEGEND-MISSING-ENTRY` | synthesize/patch a legend container from the colors actually used (labels from profile role names) |
| `W-LABEL-ARROW-OVERLAP` | nudge the label's position along its edge (mxGeometry x offset) away from the crossing segment |
| `W-EDGE-TOO-SHORT` | widen the relevant layer gap and reflow downstream y-coordinates |

Fixes stay geometry/style-only and idempotent; anything requiring intent
(layer reassignment, edge label wording) remains agent territory, and the
SKILL.md rule "two failed fixes on one region → recompute from the plan"
stays.

### B4. SKILL.md loop and delivery changes

- Step 4 loop condition becomes: **errors == 0 AND score ≥ 95 (100 when
  reachable)**, using `score_breakdown` to pick the next fix; stop when the
  score plateaus across two iterations and report the residual findings
  honestly.
- Delivery line reports the score explicitly: "Quality gate: PASS, score
  98/100 (34 nodes, 41 edges, 0 errors, 1 warning) — visually verified;
  style-conformant with template.png."
- `references/quality-rules.md` gains the new style rules and the expanded
  auto-fix table; `references/layout-recipes.md` gains a short "or run
  layout_engine.py" pointer with the JSON spec format.

## Evals & acceptance criteria

Extend `evals/evals.json` (and the workspace `grade_run.py` conventions):

1. **Template-match eval (new).** Ship a fixture template (one `.drawio` +
   its exported `.svg` and `.png`, deliberately non-house-style: different
   palette, square corners, larger fonts). Task: "diagram system X to match
   this template." Graded expectations: (a) extracted profile matches known
   ground truth on ≥90% of high-confidence fields, per input format; (b)
   output passes the gate **with `--style`** at zero style errors; (c) output
   uses ≥90% profile colors and 0 off-palette fills.
2. **Score-maximization eval (new).** A dense prompt (~35 nodes, cross-layer
   edges, multiple categories — the shape of input that produced 13 warnings
   in the iteration-1 without-skill run). Expectations: PASS with **score ≥ 95**
   and ≤1 warning; with-skill must beat without-skill score by ≥10 points.
3. **Regression.** Existing ecommerce/pipeline evals must still pass with
   identical expectations (no template supplied → default profile → today's
   behavior); `--fix` on the iteration-1 outputs must not lower any score.
4. **Determinism.** `extract_style.py` on `.drawio`/`.svg` fixtures and
   `layout_engine.py` on a fixed spec are byte-stable across runs.

## Sequencing and effort

| Phase | Work | Depends on | Size |
|---|---|---|---|
| 1 | Style-profile schema + `default.json` + score breakdown / `--target-score` in gate | — | S |
| 2 | `extract_style.py` (.drawio tier, then .svg tier) + `--style` conformance rules in gate | 1 | M |
| 3 | PNG tier (pixel histogram + vision checklist doc) + renderer profile support + SKILL.md Step 1b / Step 6 updates | 2 | M |
| 4 | Auto-fixer extension (B3 table) | 1 | M |
| 5 | `layout_engine.py` + layout-recipes pointer | 1 | M–L |
| 6 | Evals (template-match, score-max, regression) + reference-doc updates | 2–5 | S–M |

Phases 2–3 deliver goal (1); phases 4–5 deliver goal (2); either track can ship
independently after phase 1.

## Risks & mitigations

- **Over-fitting the gate to the template** — a template with cramped spacing
  could push the profile below the gate's hard floors. Rule: geometry floors
  (min gap, padding, overlap) always win over profile spacing; profile spacing
  only *raises* targets. Document the precedence in the schema.
- **Vision-extracted profiles drifting** — keep PNG-tier fields marked
  low-confidence; the gate treats low-confidence style mismatches as warnings,
  not errors, so a shaky extraction can't hard-block delivery.
- **Auto-fix oscillation** (recentering fights separation) — run fixes in a
  fixed order (containment → separation → spacing → centering → style →
  legend), cap at 3 passes, and require the score to be monotonically
  non-decreasing; abort the fix pass and report if it isn't.
- **Score inflation temptation** — never "fix" a finding by weakening a weight
  or tolerance; calibration changes require a visually-clean reference diagram
  that demonstrates the false positive (this is how the current tolerances
  were set, per the gate's header comment).
- **Zero-dependency guarantee** — every new script remains stdlib-only,
  including the PNG histogram (zlib/struct, no Pillow). This is the skill's
  defensible advantage per the comparison research; do not trade it away.

## Explicitly not in this plan

Diagram-type presets (ERD/UML/sequence), vendor stencil rendering, codebase-to-
diagram, PNG-embedded XML, and MCP live editing — all valuable (see
`compare-drawio-diagram-skill.md` recommendations) but orthogonal to the two
goals here; keeping them out keeps phases 1–6 shippable.
