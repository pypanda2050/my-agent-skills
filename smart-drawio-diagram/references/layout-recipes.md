# Layout recipes — compute coordinates before writing XML

Professional diagrams are arithmetic, not aesthetics. Decide the structure,
compute every coordinate, then write XML once. Eyeballed coordinates are why
LLM-generated diagrams stack and overlap.

## Constants

```
NODE_W=160  NODE_H=60          # standard service box
DB_W=140    DB_H=70            # cylinders need extra height for the cap
ACTOR_W=60  ACTOR_H=80
H_GAP=60                       # min horizontal gap between siblings (gate: ≥16)
V_GAP=100                      # min vertical gap between layers (room for edge labels)
C_TITLE=30  C_PAD=20           # container title strip and inner padding
ZONE_GAP=60                    # gap between adjacent containers
```

## Recipe A — layered top-down (the default for architecture)

1. **Assign layers.** Compute each node's rank = longest path from any source
   node (topological). Clients rank 0, edge/gateway rank 1, services rank 2,
   data stores rank 3, external systems either rank 4 or a separate column.
2. **Size each container from its contents.** For `n` children in one row:
   `zone_w = n*NODE_W + (n+1)*H_GAP`, `zone_h = C_TITLE + C_PAD + NODE_H + C_PAD`.
   More than ~6 children → wrap to `rows = ceil(n/6)` and
   `zone_h = C_TITLE + rows*NODE_H + (rows+1)*C_PAD`.
3. **Stack containers.** `zone_y[i] = zone_y[i-1] + zone_h[i-1] + ZONE_GAP`.
   Center narrower containers on the widest one:
   `zone_x = (max_w - zone_w)/2 + margin`.
4. **Place children with RELATIVE coordinates.** Child j (0-based) in one row:
   `x = H_GAP + j*(NODE_W + H_GAP)` … actually distribute evenly:
   `x = (zone_w - n*NODE_W - (n-1)*H_GAP)/2 + j*(NODE_W + H_GAP)`,
   `y = C_TITLE + C_PAD` (+ `row*(NODE_H + C_PAD)` for wrapped rows).
5. **Order within layers to cut crossings** (see below) before finalizing x.

## Recipe B — left-to-right pipeline

Same math with axes swapped: layers become columns, `V_GAP` between columns
becomes 120 (edge labels sit ON horizontal segments, they need width), nodes
within a column stack vertically with 40px gaps.

## Recipe C — hub-and-spoke / mesh (service meshes, integrations)

Put the hub in the center; place spokes on a circle of radius
`r ≥ (n_spokes * (NODE_W + 40)) / (2π)` — smaller radii guarantee overlaps.
Round positions to the 10px grid. For >12 spokes, prefer Recipe A with the hub
as its own layer; radial diagrams degrade fast.

## Crossing reduction (barycenter pass)

After assigning layers, order each layer by the average x-index of each node's
neighbors in the previous layer (barycenter heuristic):

```
for each layer L (top→bottom):
    for node in L: key = mean(index of connected nodes in layer L-1) or keep
    sort L by key, then recompute x positions
```

One top-down sweep followed by one bottom-up sweep removes most crossings.
This is exactly what the gate's W-CROSSINGS warning is nudging you toward.

## Edge discipline

- Vertical flow: pin `exitX=0.5;exitY=1` and `entryX=0.5;entryY=0` so edges
  leave bottoms and enter tops. Predictable ports = no surprise routes.
- Several edges into one node (e.g. every service → one DB): fan the entry
  points: `entryX=0.25 / 0.5 / 0.75;entryY=0`.
- Skip-layer edges (rank 0 → rank 3) hug the outside: add one waypoint at
  `x = diagram_right + 40` (or left) so they don't tunnel through middle layers.
- Cross-links inside a layer: route below/above the row with two waypoints.

## Worked example (3 zones, 8 nodes)

```
Zones: Clients(2) / Services(4) / Data(2), widest = services zone
services: w = 4*160 + 5*60 = 940, h = 30+20+60+20 = 130
clients:  w = 2*160 + 3*60 = 620 → x = 60 + (940-620)/2 = 220
data:     w = 2*140 + 3*60 = 460 → x = 60 + (940-460)/2 = 300
zone y:   clients 40 → h=130; services 40+130+60=230; data 230+130+60=420
child in services, slot j: x = 60 + j*220, y = 50   (relative!)
```

Sanity-check totals: the full drawing is ~1060×510 — comfortably within a 4:1
aspect ratio, with every gap ≥60px. If your computed drawing exceeds ~2500px in
one direction, wrap layers or split the diagram.

## When the gate keeps failing

Two failed fix attempts on the same region = the plan is wrong, not the
coordinates. Typical root causes: a layer with too many nodes (wrap it), a
container sized before its children were counted (recompute from step 2), or
absolute coordinates written for container children (recompute as relative).
