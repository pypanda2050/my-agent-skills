## Quality Gates (MANDATORY)

Every diagram edit MUST satisfy ALL quality gates before completion. These are **non-negotiable** — a diagram that violates any gate is invalid. After every edit, run the full validation checklist before committing.

### QG-1: Box Centering — No Off-Center Elements

All child elements MUST be mathematically centered within their parent container. Visual approximation is not acceptable — compute exact positions.

**Single item centering:**
```
child_x = parent_x + (parent_width - child_width) / 2
child_y = parent_y + (parent_height - child_height) / 2 // if vertical centering needed
```

**Multiple items in a row (equal width):**
```
gap = 10 // pick one gap value per group and use it consistently
total_width = N * item_width + (N - 1) * gap
start_x = parent_x + (parent_width - total_width) / 2

item[i].x = start_x + i * (item_width + gap)
```

**Multiple items in a row (variable width):**
```
total_width = sum(all item widths) + (N - 1) * gap
start_x = parent_x + (parent_width - total_width) / 2

item[0].x = start_x
item[1].x = item[0].x + item[0].width + gap
item[2].x = item[1].x + item[1].width + gap
...
```

**Validation:** For every child element, verify `child_x + child_width/2 ≈ parent_x + parent_width/2` (within 2px tolerance for rounding). If not centered, recalculate.

### QG-2: Even Spacing — Arithmetic Progression

Elements within the same logical group MUST have consistent spacing. Spacing MUST be computed arithmetically, never approximated.

**Rules:**
- Pick ONE vertical gap and ONE horizontal gap per group (e.g., 10px)
- All items in the same row: identical horizontal gap between adjacent items
- All rows in the same group: identical vertical gap between rows
- Gap between a group label and the first row of items: consistent (e.g., 25-30px)
- Gap between the last row and the group boundary bottom: matches top padding

**Validation:** For each group, compute `item[i+1].y - item[i].y - item[i].height` for all adjacent vertical items — all values must be equal. Same for horizontal: `item[i+1].x - item[i].x - item[i].width`.

### QG-3: No Arrow-Box Crossing

No arrow may pass through a box it is not connected to. This is the most common layout defect.

**Validation steps:**
1. For each edge, trace its full path: source exit point → all waypoints → target entry point
2. For each segment of the path, check if it intersects ANY box's bounding rectangle (x, y, width, height) that is not the source or target
3. If crossing detected:
- Option A: Add waypoints to route the arrow around the box (add 20px clearance)
- Option B: Reposition the box to eliminate the crossing
- Option C: Change the exit/entry points to avoid the crossing path

**Common crossing scenarios to check:**
- Vertical arrows passing through horizontally adjacent boxes
- Horizontal arrows passing through vertically stacked boxes
- Diagonal paths through clustered elements

### QG-4: No Arrow-Label Overlap

No arrow line may cross or overlap another arrow's label text. Labels must be fully readable.

**Validation:**
1. For each edge label, determine its bounding box (position + text dimensions)
2. Check that no other edge's line segments pass through that bounding box
3. If overlap detected:
- Move the label using `lineTValue` (0-1, position along edge)
- Add waypoints to reroute the crossing arrow
- Reposition one of the edges entirely

### QG-5: Arrow Length for Labels

Arrows MUST be long enough to display their label text without truncation or crowding.

**Minimum lengths:**
| Label Length | Minimum Visible Edge Length |
|-------------|---------------------------|
| Short (1-5 chars, e.g., "HTTPS") | 60px |
| Medium (6-15 chars, e.g., "Process Order") | 120px |
| Long (16+ chars, e.g., "Asynchronous Notifications") | 180px |

**Validation:** Measure the straight-line distance of the longest visible segment. If shorter than the minimum, extend the edge by adding waypoints or increasing distance between source/target.

### QG-6: No Overlapping Elements

No two elements may overlap unless one is explicitly a container/parent of the other.

**Validation for each pair of sibling elements:**
```
overlap = NOT (A.x + A.width < B.x OR B.x + B.width < A.x OR
A.y + A.height < B.y OR B.y + B.height < A.y)
```

If overlap is true and neither element is the parent of the other → invalid.

**Common overlap scenarios:**
- Labels extending beyond their container
- Items in adjacent groups overlapping at boundaries
- Edge labels overlapping with nearby boxes

### QG-7: Consistent Styling Per Category

Elements of the same logical category MUST use identical styling. No ad-hoc color or font variations.

**Validation:**
- Extract all elements of each category (e.g., all "third party" items)
- Verify identical: `fillColor`, `strokeColor`, `fontColor`, `fontSize`, `strokeWidth`, `rounded`
- Any deviation → fix to match the category standard

### QG-8: Legend Accuracy

Every diagram page with more than one visual category MUST include a legend. The legend MUST:

1. Include an entry for every distinct visual category used on that page
2. Use the exact same styling as the elements it describes (same `fillColor`, `strokeColor`)
3. Use accurate category names that match the diagram content
4. Not include categories that don't appear on the page

**Validation:** For each legend entry, find at least one matching element on the page. For each distinct style on the page, find a matching legend entry.

### QG-9: Container Boundary Padding

Group boundaries MUST have consistent internal padding around their children.

**Rules:**
- Minimum padding from any child to the container edge: 15px
- Top padding (below label): 25-30px to accommodate the group title
- Bottom padding: 15-20px
- Left/right padding: 15-20px
- Padding must be consistent across all containers on the same page

---

