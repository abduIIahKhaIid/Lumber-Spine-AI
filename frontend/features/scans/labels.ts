/**
 * Label placement for level boxes on an MRI slice. Mirrors backend/app/ml/render.py:
 * right-side levels prefer a label left of the box (patient right = viewer left),
 * left-side levels prefer the right, and no label covers another label or any box.
 */
export type LabelInput = {
  box: [number, number, number, number];
  side: "left" | "right" | null;
  width: number;
  height: number;
};
export type Rect = [number, number, number, number];

function area(a: Rect, b: Rect, gap = 0): number {
  const w = Math.min(a[2], b[2]) + gap - Math.max(a[0], b[0]);
  const h = Math.min(a[3], b[3]) + gap - Math.max(a[1], b[1]);
  return Math.max(0, w) * Math.max(0, h);
}

export function placeLabels(
  items: LabelInput[],
  imageWidth: number,
  imageHeight: number,
  pad: number,
): Rect[] {
  const gap = Math.max(2, pad / 2);
  const boxes = items.map((item) => item.box as Rect);
  const placed: Rect[] = [];
  const result: Rect[] = items.map(() => [0, 0, 0, 0]);
  const order = items
    .map((_, i) => i)
    .sort((a, b) => boxes[a][1] - boxes[b][1] || boxes[a][0] - boxes[b][0]);
  for (const i of order) {
    const [x0, y0, x1, y1] = boxes[i];
    const { width: w, height: h, side } = items[i];
    const cy = (y0 + y1) / 2 - h / 2;
    const left: [number, number] = [x0 - pad - w, cy];
    const right: [number, number] = [x1 + pad, cy];
    const above: [number, number] = [(x0 + x1) / 2 - w / 2, y0 - pad - h];
    const below: [number, number] = [(x0 + x1) / 2 - w / 2, y1 + pad];
    const anchors =
      side === "right"
        ? [left, above, below, right]
        : side === "left"
          ? [right, above, below, left]
          : [right, left, above, below];
    let best: Rect | null = null;
    let bestCost = Infinity;
    for (let step = 0; step < 7 && bestCost >= 1; step++) {
      const shifts = step === 0 ? [0] : [step * (h + gap), -step * (h + gap)];
      for (const [ax, ay] of anchors) {
        for (const dy of shifts) {
          const x = Math.min(Math.max(0, ax), imageWidth - w);
          const y = Math.min(Math.max(0, ay + dy), imageHeight - h);
          const rect: Rect = [x, y, x + w, y + h];
          let cost = Math.abs(dy) * 0.01 + (x !== ax ? 0.5 : 0);
          for (const other of placed) cost += area(rect, other, gap) * 4;
          for (const box of boxes) cost += area(rect, box);
          if (cost < bestCost) {
            best = rect;
            bestCost = cost;
          }
        }
      }
    }
    placed.push(best!);
    result[i] = best!;
  }
  return result;
}

/** Point on a rectangle's edge closest to (x, y). */
export function nearestOnRect(rect: Rect, x: number, y: number): [number, number] {
  return [Math.min(Math.max(x, rect[0]), rect[2]), Math.min(Math.max(y, rect[1]), rect[3])];
}
