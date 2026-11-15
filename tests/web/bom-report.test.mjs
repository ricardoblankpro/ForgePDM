import test from "node:test";
import assert from "node:assert/strict";
import {reportRows, reportMass, reportSummary} from "../../src/forgepdm/web/bom-report.mjs";

test("server report rows retain exact quantities and occurrence paths while expanding", () => {
  const root = {row_key:"a", level:1, parent_key:null, quantity:"3"};
  const child = {row_key:"a/x", level:2, parent_key:"a", quantity:"12.0000000000000001"};
  const other = {row_key:"b", level:1, parent_key:null, quantity:"2"};
  const secondChild = {...child, row_key:"b/x", parent_key:"b", quantity:"8"};
  const report = {views:{indented:[root,child,other,secondChild], direct:[root,other], flattened:[{...child,row_key:"flat:x",parent_key:null,level:1,quantity:"20.0000000000000001"}]}};
  assert.equal(reportRows(report,"indented",new Set()).length,2);
  const rows = reportRows(report,"indented",new Set(["a"]));
  assert.deepEqual(rows.map(v=>v.key),["a","a/x","b"]);
  assert.equal(rows[1].line.quantity,"12.0000000000000001");
  assert.equal(reportRows(report,"flattened",new Set())[0].line.quantity,"20.0000000000000001");
  assert.equal(reportRows(report,"direct",new Set(["a"])).length,2);
});

test("mass presentation retains unavailable values, subtotals and estimates", () => {
  assert.equal(reportMass({total_mass:null},"total_mass"),"—");
  assert.equal(reportMass({total_mass:"0.0000001",mass_source:{status:"cad_estimate"}},"total_mass"),"~<0.001");
  assert.match(reportSummary({mass_kg:null,known_mass_kg:"0.08075",contains_cad_estimates:true}), /Total unavailable.*0.081 kg.*Includes CAD estimates/);
});
