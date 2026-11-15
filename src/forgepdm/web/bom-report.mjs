import { formatMass } from "./mass-display.mjs";

export const bomViews = [["direct", "Direct"], ["indented", "Indented"], ["flattened", "Flattened"]];

export function reportRows(report, view, expanded) {
  const lines = report.views[view];
  const parents = new Set(lines.map(line => line.parent_key).filter(Boolean));
  const visible = new Set();
  return lines.flatMap(line => {
    if (view === "indented" && line.parent_key && (!visible.has(line.parent_key) || !expanded.has(line.parent_key))) return [];
    visible.add(line.row_key);
    return [{ line, key: line.row_key, depth: view === "indented" ? line.level - 1 : 0,
      hasChildren: view === "indented" && parents.has(line.row_key), expanded: expanded.has(line.row_key) }];
  });
}

export function reportMass(line, field) {
  if (line[field] == null) return "—";
  return `${line.mass_source?.status === "cad_estimate" ? "~" : ""}${formatMass(line[field])}`;
}

export function reportSummary(mass) {
  const value = mass.mass_kg == null ? `Total unavailable. Known subtotal: ${formatMass(mass.known_mass_kg)} kg` : `Assembly mass: ${formatMass(mass.mass_kg)} kg`;
  return value + (mass.contains_cad_estimates ? " · Includes CAD estimates." : "");
}
