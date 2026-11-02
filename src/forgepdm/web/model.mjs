// Pure display/navigation helpers. BOM quantities remain exact server strings.
export function readRoute(hash) {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  return { itemId: params.get("item"), revisionId: params.get("revision") };
}
export function routeFor(itemId, revisionId) {
  const params = new URLSearchParams({ item: itemId });
  if (revisionId) params.set("revision", revisionId);
  return `#${params}`;
}
export function bomRows(lines, expanded, multilevel = true, ancestry = []) {
  const rows = [];
  for (const line of lines) {
    const path = [...ancestry, line.id];
    const key = JSON.stringify(path);
    rows.push({ line, key, depth: ancestry.length,
      hasChildren: multilevel && Boolean(line.children?.length),
      expanded: expanded.has(key) });
    if (multilevel && expanded.has(key)) {
      rows.push(...bomRows(line.children || [], expanded, true, path));
    }
  }
  return rows;
}
export function allBomKeys(lines, ancestry = []) {
  return lines.flatMap(line => {
    const path = [...ancestry, line.id];
    return [JSON.stringify(path), ...allBomKeys(line.children || [], path)];
  });
}
export function fileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
export function dateLabel(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short"
  }).format(date);
}
export function stateLabel(value) {
  return ({ working: "Working", released: "Released", obsolete: "Obsolete" })[value] || value;
}
