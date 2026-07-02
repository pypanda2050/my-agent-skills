# .drawio (mxGraph XML) essentials

## File skeleton — always write uncompressed

```xml
<mxfile host="app.diagrams.net" modified="2026-01-01T00:00:00Z" agent="smart-drawio-diagram" version="24.0.0">
  <diagram id="page1" name="Architecture">
    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" tooltips="1"
                  connect="1" arrows="1" fold="1" page="1" pageScale="1"
                  pageWidth="1600" pageHeight="1200" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- your cells here, parent="1" for top level -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Cells `0` and `1` are mandatory scaffolding. Everything you add has
`parent="1"` (top level) or `parent="<container-id>"` (inside a container).

Set `pageWidth`/`pageHeight` generously (diagram bounds + 100px); the tools
ignore them but draw.io uses them for the printed page.

## Vertices (nodes)

```xml
<mxCell id="api_gw" value="API Gateway" style="rounded=1;whiteSpace=wrap;html=1;arcSize=10;fillColor=#d5e8d4;strokeColor=#82b366;"
        vertex="1" parent="services_zone">
  <mxGeometry x="40" y="50" width="160" height="60" as="geometry"/>
</mxCell>
```

- `id`: unique, snake_case, human-readable (`orders_db`, not `node17`). The
  quality gate reports ids, so readable ids make fixing faster.
- `value`: the label. Keep ≤3 words per line; use `&#10;` or `<br>` for manual
  breaks. `whiteSpace=wrap` makes text wrap at the box width.
- **Coordinates of children are relative to the parent container's top-left.**
  This is the most common LLM mistake — writing absolute coordinates for
  container children throws them far outside the container.

## Containers (zones / layers)

```xml
<mxCell id="services_zone" value="Backend Services" style="swimlane;startSize=30;horizontal=1;fillColor=#e3f2fd;strokeColor=#7f9db9;fontSize=13;fontStyle=1;whiteSpace=wrap;html=1;rounded=1;arcSize=4;"
        vertex="1" parent="1">
  <mxGeometry x="60" y="180" width="640" height="170" as="geometry"/>
</mxCell>
```

`startSize=30` reserves a 30px title strip at the top — children must start at
`y ≥ 50` (30 title + 20 padding) or the gate flags E-CONTAINER-FIT.

## Edges

```xml
<mxCell id="e_gw_orders" value="gRPC" style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;jettySize=auto;orthogonalLoop=1;strokeColor=#666666;fontSize=11;"
        edge="1" parent="1" source="api_gw" target="orders_svc">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

- `source`/`target` are REQUIRED (dangling edges fail the gate).
- `parent="1"` even when endpoints live inside containers — edges belong to the
  top level unless both endpoints share the same container.
- Label every edge with protocol or payload (`HTTPS/REST`, `SQL`, `events`,
  `gRPC`, `S3 PUT`). Dashed for async: append `dashed=1;`.
- To force a route around an obstacle, add explicit waypoints (ABSOLUTE
  coordinates):

```xml
<mxGeometry relative="1" as="geometry">
  <Array as="points"><mxPoint x="520" y="410"/></Array>
</mxGeometry>
```

- To pin which side an edge leaves/enters: `exitX=0.5;exitY=1;entryX=0.5;entryY=0;`
  (fractions of the node box: this example = leave bottom-center, enter top-center).
  Pinning exits/entries to match the flow direction makes orthogonal routing
  predictable and is the main tool for fixing W-EDGE-THROUGH warnings.

## Node style catalog

| Purpose | style string core |
|---|---|
| Service / app (default) | `rounded=1;whiteSpace=wrap;html=1;arcSize=10;` |
| Database | `shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;` |
| Queue / stream | `shape=mxgraph.flowchart.internal_storage;whiteSpace=wrap;html=1;` |
| External / 3rd-party | `rounded=1;whiteSpace=wrap;html=1;dashed=1;` |
| Cloud | `ellipse;shape=cloud;whiteSpace=wrap;html=1;` |
| User / client | `shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;` |
| Decision / router | `rhombus;whiteSpace=wrap;html=1;` |
| Cache | `shape=cylinder3;whiteSpace=wrap;html=1;size=15;` + cache color |

Prefer this vocabulary — the bundled SVG renderer draws all of it faithfully.
Cloud-provider icon stencils (`mxgraph.aws4.*` etc.) work in draw.io but render
as plain boxes in the fallback SVG; only use them when the draw.io CLI is
installed for export.

## Color palette (fill / stroke)

| Role | fillColor | strokeColor |
|---|---|---|
| Client / frontend | `#dae8fc` | `#6c8ebf` |
| Service / backend | `#d5e8d4` | `#82b366` |
| Database / storage | `#ffe6cc` | `#d79b00` |
| Queue / messaging | `#e1d5e7` | `#9673a6` |
| Cache | `#fff2cc` | `#d6b656` |
| External / 3rd-party | `#f5f5f5` | `#666666` |
| Infra (LB, CDN, DNS) | `#d4e1f5` | `#4a7ebb` |
| Alert / hot path | `#f8cecc` | `#b85450` |

Container fills (use 30–50% lighter tones): frontend `#fff9e6`, backend
`#eef7ee`, data `#fff3e6`, external `#f5f5f5`, infra `#eaf1fb`. One color per
tier, consistently — color is information, not decoration.

## Fonts

Node labels `fontSize=12`, container titles `fontSize=13;fontStyle=1`, edge
labels `fontSize=11`. The gate's text-fit estimate assumes these defaults; if
you enlarge fonts, enlarge boxes to match.
