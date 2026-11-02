import test from "node:test";
import assert from "node:assert/strict";
import { readRoute, routeFor, bomRows, allBomKeys, fileSize } from "../../src/forgepdm/web/model.mjs";

test("navigation preserves the explicitly selected historical revision", () => {
  assert.deepEqual(readRoute(routeFor("item-1", "revision-A")), { itemId: "item-1", revisionId: "revision-A" });
  assert.deepEqual(readRoute(routeFor("item-1")), { itemId: "item-1", revisionId: null });
  assert.deepEqual(readRoute(""), { itemId: null, revisionId: null });
});
test("multilevel expansion scopes repeated subassembly lines by occurrence path", () => {
  const child = { id: "shared-child", item_number: "PART", component_revision_id: "part-A", quantity: "0.1250000000000001" };
  const lines = [{ id: "first", children: [child] }, { id: "second", children: [child] }];
  const expanded = new Set([JSON.stringify(["first"])]);
  const rows = bomRows(lines, expanded);
  assert.equal(rows.length, 3);
  assert.equal(rows[1].line.component_revision_id, "part-A");
  assert.equal(rows[1].line.quantity, "0.1250000000000001");
  assert.equal(rows[1].depth, 1);
  assert.equal(new Set(allBomKeys(lines)).size, 4);
  assert.equal(bomRows(lines, new Set(allBomKeys(lines))).length, 4);
  assert.equal(bomRows(lines, expanded, false).length, 2);
});
test("file-size labels handle empty and large files", () => {
  assert.equal(fileSize(0), "0 B");
  assert.equal(fileSize(1024), "1.0 KB");
  assert.equal(fileSize(1024 ** 3), "1.00 GB");
});
