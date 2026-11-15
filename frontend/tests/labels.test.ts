import { test } from "node:test";
import assert from "node:assert/strict";
import { placeLabels, type Rect } from "../features/scans/labels.ts";

const overlap = (a: Rect, b: Rect) =>
  !(a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1]);

test("subarticular labels do not overlap each other or the boxes, and keep their side", () => {
  const items = [
    { box: [80, 115, 155, 190] as Rect, side: "right" as const, width: 60, height: 18 },
    { box: [135, 130, 215, 212] as Rect, side: "left" as const, width: 60, height: 18 },
    { box: [90, 200, 150, 260] as Rect, side: "right" as const, width: 60, height: 18 },
    { box: [140, 205, 200, 262] as Rect, side: "left" as const, width: 60, height: 18 },
  ];
  const rects = placeLabels(items, 320, 320, 5);
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++)
      assert.ok(!overlap(rects[i], rects[j]), `labels ${i} ${j}`);
    for (const item of items) assert.ok(!overlap(rects[i], item.box), `label ${i} covers a box`);
  }
  assert.ok(rects[0][2] <= items[0].box[0], "right-side label sits left of its box");
  assert.ok(rects[1][0] >= items[1].box[2], "left-side label sits right of its box");
});
