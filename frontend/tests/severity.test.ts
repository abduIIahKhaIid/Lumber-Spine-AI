import { test } from "node:test";
import assert from "node:assert/strict";
import { SEVERITIES, percent, rank, styleFor } from "../lib/severity.ts";

test("severity colors are green, yellow and red in grade order", () => {
  assert.deepEqual(SEVERITIES, ["Normal/Mild", "Moderate", "Severe"]);
  assert.equal(styleFor("Normal/Mild").fill, "#22c55e");
  assert.equal(styleFor("Moderate").fill, "#eab308");
  assert.equal(styleFor("Severe").fill, "#ef4444");
  assert.equal(styleFor("unknown").short, "Unknown");
  assert.ok(rank("Severe") > rank("Moderate"));
  assert.equal(percent(0.456), "46%");
  assert.equal(percent(null), "–");
});
