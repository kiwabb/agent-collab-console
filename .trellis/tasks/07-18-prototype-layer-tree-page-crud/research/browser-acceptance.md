# Browser Acceptance Evidence

Date: 2026-07-19

Target:
`http://localhost:4000/projects/09cca906-b5e1-4601-aa7a-14fb58f9f06b/prototypes`

Environment:

- Frontend: `http://localhost:4000`
- Backend: `http://127.0.0.1:9000`
- Clean browser origin: `localhost` (the separate `127.0.0.1` tab retained
  intentionally stale pending-operation evidence and was not used).

## Page CRUD and Ordering

1. Entered Studio full-screen mode.
2. Added a blank page: page count `3 -> 4`, document `192 -> 193`.
3. Renamed it to `QA 验收页`: document `193 -> 194`.
4. Duplicated it: `QA 验收页副本`, route `/page-copy`, page count `4 -> 5`,
   document `194 -> 195`.
5. Found and fixed a real acceptance blocker: the full-screen Studio root was
   `z-[100]`, above body-portaled Dialog chrome at `z-50`. The confirmation was
   present in the accessibility tree but visually covered and pointer-inert.
   Lowering the Studio root to `z-40` made the same open dialog visible and
   operable.
6. Deleted the duplicate: page count `5 -> 4`, document `195 -> 196`; the
   deterministic nearest survivor became active.
7. Dragged `QA 验收页` below `用户管理`: order became
   `仪表盘, 用户管理, QA 验收页, 订单管理`, document `210 -> 211`.
8. Dragged it back before `用户管理`: original order restored, document
   `211 -> 212`.
9. Deleted `QA 验收页`: final pages are `仪表盘, 用户管理, 订单管理`, document
   `212 -> 213`.
10. Reloaded and confirmed document `213` and the same three-page order.

## Layer Tree and Commands

- Roving focus: Arrow Down, Home, End, Arrow Right, and Arrow Left moved through
  the visible hierarchy and updated the sole `tabIndex=0` treeitem.
- Enter selected `页面标题`. Clicking the fourth-level canvas node
  `页面主标题` revealed both ancestors and selected the matching treeitem.
- F2 opened inline rename. A whitespace-only value showed
  `请输入图层名称。` without advancing the document.
- Renamed to `QA 主标题`: document `196 -> 197`.
- Pressed V to hide it: document `197 -> 198`; the tree retained the hidden
  node while the canvas stopped rendering it.
- Undo visibility and rename: documents `198 -> 199 -> 200`.
- Redo rename and visibility: documents `200 -> 201 -> 202`.
- Reloaded at document `202`; name and hidden state persisted. Two Undo actions
  restored `页面主标题` and visible state at document `204`.
- Dragged top-level `按钮` inside `最近动态`: document `204 -> 205`; the tree
  level changed `2 -> 3` and the canvas node became a child of that Stack.
- Undo restored the top-level node at document `206`.
- A calibration drag repeated the same valid inside destination at document
  `207`; Undo restored it at document `208`.
- Dragged `自由画布` before `按钮`: document `208 -> 209`, DnD status named the
  `prototype-layer:drop:before` target.
- Dragged it after `按钮`: document `209 -> 210`, original order restored and
  DnD status named `prototype-layer:drop:after`.

## Narrow Viewport and Failure State

- Set the browser viewport to `390 x 844` and opened the `页面与图层` drawer.
- Dragged `页面标题` inside its descendant `标题文案`.
- The document stayed at `210`; both the canvas surface and the open mobile
  drawer displayed `该组件不能移动到这个位置`.
- Reset the viewport to the default `1280 x 720` before completion.

## Final State

- Final document: `doc 213`.
- Final pages: `仪表盘`, `用户管理`, `订单管理`.
- Final node name, visibility, and top-level order match the pre-QA document.
- Full-screen mode was left open for handoff.
- Browser console errors: `[]`.
- Browser screenshots were captured for the full-screen deletion dialog, the
  narrow drawer refusal, and the final desktop state in the acceptance task.

## Selection Chrome Regression

- Re-tested the Fit desktop canvas after removing the selection Grip entirely.
  The selected Button exposed four invisible move bands on the selection edges;
  each band was 10 client pixels thick. Its resize markers measured `8 x 8`
  inside the existing transparent transform hit areas.
- The selected control DOM contained no `.lucide-grip-vertical`. Freeform
  hierarchy movement still exposed its separate `Layers3` reparent control.
- Started a canvas-node drag from the selection surface with the keyboard sensor.
  The controls layer reported `hidden-during-node-drag`; the outline became
  transparent, all three Button resize handles were visibility-hidden, the
  activator stayed mounted, and the faithful business mirror remained visible.
- Pressed Escape. The controls layer returned to `visible`, the mirror detached,
  and the outline and resize controls returned with correct geometry.
- A pointer drag from the top edge independently proved that the edge starts the
  real node DnD path. It landed in an adjacent slot during QA (`doc 214 -> 215`),
  so the structured Undo command restored the original top-level order at
  `doc 216`: `页面标题, 核心指标, 最近动态, 按钮, 自由画布`.
- Final Studio state was saved, selection chrome was `visible`, selected-control
  Grip count was `0`, and browser console errors were `[]`.
