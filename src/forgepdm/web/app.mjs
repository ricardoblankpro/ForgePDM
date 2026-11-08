import { materialsUI } from "./materials.mjs";
import { managementUI } from "./management.mjs";
import { drawingViewer } from "./drawings.mjs";
import { API } from "./api.mjs";
import { readRoute, routeFor, bomRows, allBomKeys, fileSize, dateLabel, stateLabel } from "./model.mjs";

const $ = selector => document.querySelector(selector);
const api = new API();
const state = { user: null, projects: [], items: [], query: "", project: "", offset: 0,
  hasMore: false, item: null, revision: null, revisions: [], tab: "overview",
  cache: {}, expanded: new Set(), multilevel: true, page: "catalog", historyAll: false };
let session = new AbortController();
let listVersion = 0;
let detailVersion = 0;
let tabVersion = 0;
let toastTimer;
let management;
const materialUI = materialsUI({api, el, button, state, descriptionSaved(revision,record) {
  if(state.revision?.id===revision.id)state.revision.description_record=record;
  for(const item of state.items)if(item.current_revision_id===revision.id)item.revision_description=record.description;
  renderItems();
  const title=document.querySelector(".detail-name");
  if(title&&state.revision?.id===revision.id)title.textContent=record.description||state.item.name;
}});
document.querySelector("#new-material").addEventListener("click", async()=>{
  const host=document.querySelector("#detail");
  materialUI.create(host, item=>navigate(item.id,item.current_revision_id));
});
const drawingUI = drawingViewer({ state, request, el, button, dateLabel });

function el(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name.startsWith("on")) element.addEventListener(name.slice(2).toLowerCase(), value);
    else if (name === "class") element.className = value;
    else if (name === "value") element.value = value;
    else if (value !== false && value != null) element.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child != null && child !== false) element.append(child);
  }
  return element;
}
function icon(kind = "part") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.35");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(svg.namespaceURI, "path");
  path.setAttribute("d", kind === "assembly" ?
    "m3 7 9-5 9 5-9 5Z M3 7v10l9 5 9-5V7 M12 12v10 M3 12l9 5 9-5" :
    "m4 7 8-4 8 4v10l-8 4-8-4Z M4 7l8 4 8-4 M12 11v10");
  svg.append(path);
  return svg;
}
function badge(value) { return el("span", { class: `badge ${["working", "released", "obsolete"].includes(value) ? value : ""}` }, stateLabel(value)); }
function button(text, handler, attrs = {}) { return el("button", { type: "button", onClick: handler, ...attrs }, text); }
function loading(text = "Loading…") { return el("div", { class: "loading", role: "status" }, el("span", { class: "spinner", "aria-hidden": "true" }), text); }
function empty(title, text, kind = "part") {
  return el("div", { class: "empty-state" }, el("div", { class: "empty-symbol" }, icon(kind)), el("h2", {}, title), el("p", {}, text));
}
function showError(target, error, retry) {
  if (error.name === "AbortError" || !state.user) return;
  target.replaceChildren(el("div", { class: "inline-error", role: "alert" },
    el("div", {}, error.message || "The server could not be reached."),
    retry && button("Try again", retry, { class: "secondary" })));
}
function toast(message) {
  $("#toast").textContent = message; $("#toast").hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 5000);
}
function request(path, options = {}) { return api.request(path, { signal: session.signal, ...options }); }
function resetSession(message = "") {
  drawingUI.reset();
  management?.reset();
  session.abort(); session = new AbortController(); api.token = null;
  listVersion++; detailVersion++; tabVersion++;
  Object.assign(state, { user: null, items: [], projects: [], item: null, revision: null, revisions: [], cache: {}, offset: 0, project: "", query: "", page: "catalog" });
  $("#workspace").hidden = true; $("#login-screen").hidden = false;
  $("#items-list").replaceChildren(); $("#detail").replaceChildren();
  $("#project-links").replaceChildren(); $("#project-cards").replaceChildren();
  $("#account-name").textContent = ""; $("#account-avatar").textContent = "";
  $("#project-filter").replaceChildren(el("option", { value: "" }, "All accessible projects"));
  $("#series-filter").value = "";
  $("#search").value = ""; $(".skip-link").setAttribute("href", "#main");
  $("#password").value = "";
  $("#login-error").textContent = message; $("#login-error").hidden = !message;
  document.title = "ForgePDM · Engineering workspace";
}
api.onExpired = () => resetSession("Your session has expired. Sign in again to continue.");

$("#login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const submit = $("#login-button"); submit.disabled = true;
  $("#login-error").hidden = true;
  try {
    const result = await api.request("/auth/login", { method: "POST", body: {
      username: $("#username").value.trim(), password: $("#password").value
    } });
    api.token = result.access_token; state.user = result.user;
    $("#password").value = "";
    $("#login-screen").hidden = true; $("#workspace").hidden = false;
    $(".skip-link").setAttribute("href", "#workspace-main");
    $("#account-name").textContent = result.user.display_name || result.user.username;
    $("#account-avatar").textContent = (result.user.display_name || result.user.username).slice(0, 2).toUpperCase();
    $("#search").value = "";
    for (const nav of document.querySelectorAll(".nav-button")) nav.hidden = result.user.must_change_password || (nav.id === "nav-users" && result.user.role !== "admin");
    document.querySelector("#nav-account").hidden = false;
    if (result.user.must_change_password) { setPage("account"); return; }
    setPage("catalog");
    renderEmptyDetail();
    loadProjects(); loadItems();
    if (readRoute(location.hash).itemId) loadDetail();
    $("#workspace-main").focus();
  } catch (error) {
    $("#login-error").textContent = error.status === 401 ? "The username or password is incorrect." : (error.message || "Could not reach ForgePDM.");
    $("#login-error").hidden = false;
  } finally { submit.disabled = false; $("#password").value = ""; }
});
$("#logout").addEventListener("click", () => {
  const revoke = api.request("/auth/logout", { method: "POST" });
  resetSession();
  revoke.catch(() => toast("Signed out locally. The server could not confirm session revocation."));
});

async function loadProjects() {
  const currentSession = session;
  try {
    const rows = await api.allPages("/projects", session.signal);
    if (currentSession !== session || !state.user) return;
    state.projects = rows;
    if (state.project && !rows.some(project => project.id === state.project)) {
      state.project = ""; state.offset = 0; loadItems();
    }
    $("#project-filter").replaceChildren(el("option", { value: "" }, "All accessible projects"),
      ...rows.map(p => el("option", { value: p.id }, `${p.project_number} · ${p.name}`)));
    $("#project-filter").value = state.project;
    $("#project-links").replaceChildren(...rows.map(p => button(p.project_number, () => chooseProject(p.id), {
      class: "project-nav", title: p.name
    })));
    if (!rows.length) $("#project-links").append(el("p", { class: "small-muted" }, "No assigned projects"));
    renderProjects();
  } catch (error) {
    if (error.name !== "AbortError" && state.user) {
      $("#project-links").replaceChildren(button("Retry loading projects", loadProjects, { class: "project-nav" }));
      showError($("#project-cards"), error, loadProjects);
    }
  }
}
function renderProjects() {
  const cards = state.projects.map(project => el("article", { class: "project-card" },
    el("div", { class: "type-icon assembly" }, icon("assembly")),
    el("h2", {}, project.project_number), el("p", {}, project.name),
    button("Browse project items →", () => chooseProject(project.id), { class: "text-button" })));
  $("#project-cards").replaceChildren(...(cards.length ? cards : [empty("No projects available", "Your assigned projects will appear here. Contact your administrator if you need access.")]));
}
function setPage(page) {
  drawingUI.reset();
  if (state.user?.must_change_password) page = "account";
  state.page = page;
  const managed = !["projects", "catalog"].includes(page);
  const titles = {catalog:"Item catalog", projects:"Projects", users:"Users", "project-settings":"Project management", checkouts:"My checkouts", activity:"Activity history", account:"My account"};
  $("#projects-panel").hidden = page !== "projects";
  $("#catalog-panel").hidden = page !== "catalog";
  $("#management-panel").hidden = !managed;
  for (const nav of document.querySelectorAll(".nav-button")) nav.classList.toggle("active", nav.id === `nav-${page}`);
  $("#page-crumb").textContent = $("#page-title").textContent = titles[page] || page;
  $("#page-subtitle").textContent = page === "projects" ? "Explore the projects you have access to." : page === "catalog" ? "Find a component. Follow its history. Understand its place." : "Manage your workspace through controlled, authorized actions.";
  if (managed) management.open(page);
}
$("#nav-catalog").addEventListener("click", () => setPage("catalog"));
$("#nav-projects").addEventListener("click", () => setPage("projects"));
function chooseProject(id) {
  state.project = id; state.offset = 0; $("#project-filter").value = id;
  setPage("catalog"); location.hash = ""; loadItems();
}
$("#project-filter").addEventListener("change", () => chooseProject($("#project-filter").value));
$("#series-filter").addEventListener("change", () => { state.offset = 0; loadItems(); });
$("#search-form").addEventListener("submit", event => {
  event.preventDefault(); state.query = $("#search").value.trim(); state.offset = 0; loadItems();
});
$("#previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 20); loadItems(); });
$("#next").addEventListener("click", () => { if (state.hasMore) { state.offset += 20; loadItems(); } });
document.addEventListener("keydown", event => {
  if (event.key === "/" && state.user && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
    event.preventDefault(); setPage("catalog"); $("#search").focus();
  }
});
async function loadItems() {
  const version = ++listVersion;
  $("#items-list").replaceChildren(loading("Loading items…"));
  $("#previous").disabled = $("#next").disabled = true;
  const params = new URLSearchParams({ q: state.query, limit: "20", offset: String(state.offset) });
  if (state.project) params.set("project_id", state.project);
  if ($("#series-filter").value) params.set("number_series", $("#series-filter").value);
  try {
    const page = await request(`/items?${params}`);
    if (version !== listVersion || !state.user) return;
    state.items = page.items; state.hasMore = page.has_more;
    renderItems();
    $("#previous").disabled = state.offset === 0; $("#next").disabled = !page.has_more;
    $("#page-number").textContent = `Page ${Math.floor(state.offset / 20) + 1}`;
    $("#list-count").textContent = `${page.items.length} on this page`;
  } catch (error) { if (version === listVersion) showError($("#items-list"), error, loadItems); }
}
function renderItems() {
  const active = readRoute(location.hash).itemId;
  $("#items-list").replaceChildren(...state.items.map(item => button([
    el("span", { class: `type-icon ${item.kind}` }, icon(item.kind)),
    el("span", { class: "item-row-copy" }, el("span", { class: "item-number" }, item.number),
      el("span", { class: "item-row-title" }, item.revision_description || item.name),
      el("span", { class: "item-row-bottom" }, `Revision ${item.revision_label}`, badge(item.lifecycle_state)))
  ], () => navigate(item.id), { class: `item-row${active === item.id ? " selected" : ""}`, "aria-current": active === item.id ? "true" : null, "aria-label": `${item.number}, ${item.revision_description || item.name}, revision ${item.revision_label}` })));
  if (!state.items.length) $("#items-list").append(el("div", { class: "list-empty" }, "No items found. Try another search or project."));
}
function navigate(itemId, revisionId) {
  setPage("catalog");
  const hash = routeFor(itemId, revisionId);
  if (location.hash === hash) loadDetail(); else location.hash = hash;
  if (matchMedia("(max-width:600px)").matches) $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
}
window.addEventListener("hashchange", () => { if (state.user) loadDetail(); });
function renderEmptyDetail() {
  $("#detail").classList.add("detail-placeholder");
  $("#detail").replaceChildren(empty("Your product data, in context", "Select an item to explore its revisions, product structure and associated files.", "assembly"));
}
async function loadDetail() {
  drawingUI.reset();
  const version = ++detailVersion; tabVersion++;
  const { itemId, revisionId } = readRoute(location.hash);
  state.item = null; state.revision = null; state.cache = {}; state.expanded = new Set(); state.historyAll = false;
  renderItems();
  if (!itemId) { renderEmptyDetail(); return; }
  $("#detail").classList.remove("detail-placeholder");
  $("#detail").replaceChildren(loading("Loading item and revision…"));
  try {
    const [item, revisions] = await Promise.all([
      request(`/items/${encodeURIComponent(itemId)}`),
      api.allPages(`/items/${encodeURIComponent(itemId)}/revisions`, session.signal)
    ]);
    if (version !== detailVersion || !state.user) return;
    const chosen = revisionId || item.current_revision_id;
    const revision = await request(`/revisions/${encodeURIComponent(chosen)}`);
    if (version !== detailVersion || !state.user) return;
    if (revision.item_id !== item.id) throw new Error("The requested revision does not belong to this item.");
    if (!revisions.some(r => r.id === revision.id)) throw new Error("The selected revision is unavailable.");
    state.item = item; state.revision = revision; state.revisions = revisions;
    state.tab = "overview";
    document.title = `${item.number} · Revision ${revision.label} · ForgePDM`;
    renderDetail();
  } catch (error) { if (version === detailVersion) showError($("#detail"), error, loadDetail); }
}
function renderDetail() {
  drawingUI.reset();
  const { item, revision } = state;
  if (!item || !revision) return;
  const picker = el("select", { id: "revision-picker", "aria-label": "Selected revision", onChange: event => navigate(item.id, event.target.value) },
    ...state.revisions.map(r => el("option", { value: r.id }, `Rev ${r.label}${r.id === item.current_revision_id ? " · current" : ""}`)));
  picker.value = revision.id;
  const header = el("div", { class: "detail-header" },
    el("div", { class: "item-kicker" }, `${item.kind} / Item details`),
    el("div", { class: "detail-title-line" }, el("h2", {}, item.number),
      el("div", { class: "revision-picker" }, el("label", { for: "revision-picker" }, "Viewing"), picker)),
    el("p", { class: "detail-name" }, revision.description_record?.description || item.name));
  const notice = revision.id !== item.current_revision_id ? el("div", { class: "revision-note" },
    `Viewing recorded revision ${revision.label}. Current revision ${item.current_revision.label} is available. `,
    button(`View ${item.current_revision.label} →`, () => navigate(item.id, item.current_revision_id), { class: "text-button" })) : null;
  const tabs = el("div", { class: "tabs", role: "tablist", "aria-label": "Item information" });
  for (const [key, label] of [["overview", "Overview"], ["materials", "Description"], ["bom", "Bill of materials"], ["drawings", "Drawings"], ["datasets", "Files & datasets"], ["where-used", "Where used"]]) {
    tabs.append(button(label, () => { state.tab = key; renderDetail(); }, {
      class: `tab${state.tab === key ? " active" : ""}`, role: "tab", id: `tab-${key}`,
      "aria-selected": String(state.tab === key), "aria-controls": "tab-content", tabindex: state.tab === key ? "0" : "-1",
      onKeydown: event => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const siblings = [...event.target.parentElement.children];
        const next = siblings[(siblings.indexOf(event.target) + (event.key === "ArrowRight" ? 1 : -1) + siblings.length) % siblings.length];
        next.click(); document.getElementById(next.id)?.focus();
      }
    }));
  }
  const content = el("div", { class: "tab-content", id: "tab-content", role: "tabpanel", "aria-labelledby": `tab-${state.tab}` });
  $("#detail").replaceChildren(header, ...(notice ? [notice] : []), tabs, content);
  loadTab(content);
}
async function loadTab(content) {
  const version = ++tabVersion;
  const revision = state.revision;
  const tab = state.tab;
  if (tab === "materials") return materialUI.render(content, state.item, revision);
  if (tab === "overview") { renderOverview(content); return; }
  if (Object.hasOwn(state.cache, tab)) { renderTabData(content, tab, state.cache[tab]); return; }
  content.replaceChildren(loading("Loading revision data…"));
  const path = tab === "bom" ? `/revisions/${revision.id}/bom?recursive=true` :
    tab === "drawings" ? `/revisions/${revision.id}/drawings` :
    tab === "datasets" ? `/revisions/${revision.id}/datasets` : `/items/${state.item.id}/where-used`;
  try {
    const data = await request(path);
    if (version !== tabVersion || state.revision?.id !== revision.id || !state.user) return;
    state.cache[tab] = data;
    if (tab === "bom") state.expanded = new Set(data.map(line => JSON.stringify([line.id])));
    renderTabData(content, tab, data);
  } catch (error) { if (version === tabVersion) showError(content, error, () => loadTab(content)); }
}
function renderOverview(content) {
  const { item, revision } = state;
  const properties = [["Number series", item.number_series || item.number[0]], ["Item type", item.kind === "assembly" ? "Assembly" : "Part"],
    ["Lifecycle state", badge(revision.lifecycle_state)], ["Selected revision", `Revision ${revision.label}`],
    ["Revision created", dateLabel(revision.created_at)]];
  const info = el("dl", { class: "info-grid" }, ...properties.map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value))));
  const rows = state.historyAll ? state.revisions : state.revisions.slice(0, 8);
  const table = dataTable(["Revision", "State", "Created", ""], rows.map(r => [
    `Rev ${r.label}`, badge(r.lifecycle_state), dateLabel(r.created_at),
    r.id === revision.id ? el("span", { class: "small-muted" }, "Viewing") : button("Open →", () => navigate(item.id, r.id), { class: "text-button", "aria-label": `Open revision ${r.label}` })
  ]), "revision-table", "Revision history");
  content.replaceChildren(el("h3", { class: "section-caption" }, "Revision information"), el("div", { class: "info-card" }, info),
    el("div", { class: "section-header" }, el("h3", {}, "Change note")),
    el("p", { class: "description" }, revision.change_note || "No change note recorded."), el("br"),
    item.standard_specification && el("div", { class: "info-card" }, el("h3", { class: "section-caption" }, "Standard specification"), el("dl", { class: "info-grid" }, ...[...Object.entries(item.standard_specification.geometry), ...["material", "grade", "finish"].map(key => [key, item.standard_specification[key] || "Unknown"])].map(([key, value]) => el("div", {}, el("dt", {}, key.replace(/([a-z])([A-Z])/g, "$1 $2")), el("dd", {}, String(value)))))),
    item.description && el("div", { class: "info-card" }, el("h3", { class: "section-caption" }, "Item description"), el("p", { class: "description" }, item.description)),
    el("div", { class: "section-header" }, el("h3", {}, "Revision history"), el("span", { class: "small-muted" }, `${state.revisions.length} revision${state.revisions.length === 1 ? "" : "s"}`)), table);
  if (state.revisions.length > 8) content.append(button(state.historyAll ? "Show recent revisions" : "Show all revisions", () => { state.historyAll = !state.historyAll; renderOverview(content); }, { class: "quiet" }));
}
function dataTable(headers, rows, className = "", label = "") {
  return el("div", { class: "table-scroll", tabindex:"0", "aria-label":`${label || "Data table"} · scroll for more columns` }, el("table", { class: `data-table ${className}`, "aria-label": label },
    el("thead", {}, el("tr", {}, ...headers.map(header => el("th", { scope: "col" }, header)))),
    el("tbody", {}, ...rows.map(row => el("tr", {}, ...row.map(cell => el("td", {}, cell)))))));
}
function renderTabData(content, tab, data) {
  if (tab === "bom") renderBOM(content, data);
  else if (tab === "datasets") renderDatasets(content, data);
  else if (tab === "drawings") drawingUI.render(content, data, () => { delete state.cache.drawings; loadTab(content); });
  else renderWhereUsed(content, data);
}
function renderBOM(content, lines) {
  const controls = el("div", { class: "bom-controls" },
    el("div", { class: "segmented", "aria-label": "BOM view" },
      ...[[false, "Direct"], [true, "Multilevel"]].map(([multi, label]) => button(label, () => { state.multilevel = multi; renderBOM(content, lines); }, {
        class: state.multilevel === multi ? "active" : "", "aria-pressed": String(state.multilevel === multi)
      }))),
    state.multilevel && el("div", { class: "compact-actions" },
      button("Expand all", () => { state.expanded = new Set(allBomKeys(lines)); renderBOM(content, lines); }, { class: "quiet" }),
      button("Collapse all", () => { state.expanded.clear(); renderBOM(content, lines); }, { class: "quiet" })));
  const rows = bomRows(lines, state.expanded, state.multilevel).map(({ line, key, depth, hasChildren, expanded }) => [
    el("div", { class: `bom-cell depth-${Math.min(depth, 12)}` }, hasChildren ? button(expanded ? "▾" : "▸", () => {
      if (expanded) state.expanded.delete(key); else state.expanded.add(key); renderBOM(content, lines);
    }, { class: "tree-toggle", "aria-expanded": String(expanded), "aria-label": `${expanded ? "Collapse" : "Expand"} ${line.item_number} revision ${line.revision_label}` }) : el("span", { class: "tree-spacer" }),
    el("div", {}, button(line.item_number, () => navigate(line.item_id, line.component_revision_id), { class: "text-button number" }), el("span", { class: "row-description", title: line.item_name }, line.item_name))),
    `Rev ${line.revision_label}`, line.quantity, badge(line.lifecycle_state)
  ]);
  content.replaceChildren(controls, ...(lines.length ? [
    dataTable(["Component", "Revision", "Qty / parent", "State"], rows, "bom-table", "Revision-pinned bill of materials"),
    el("p", { class: "small-muted" }, "Quantities are per immediate parent. Components use their recorded revision. Empty subassembly BOMs have no child rows.")
  ] : [empty("No BOM lines recorded", "This revision has no stored engineering BOM. Assembly BOMs can be reviewed and synchronized from FreeCAD.", "assembly")]));
}
function renderDatasets(content, datasets) {
  if (!datasets.length) { content.replaceChildren(empty("No files attached", "Uploaded CAD snapshots and supporting files for this revision will appear here.")); return; }
  const cards = datasets.flatMap(dataset => dataset.files.map(file => {
    const download = button("Download ↓", event => downloadFile(file, event.currentTarget), { class: "secondary", "aria-label": `Download ${file.original_filename}` });
    return el("article", { class: "file-card" },
      el("div", { class: "file-topline" }, el("div", {}, el("p", { class: "file-name" }, file.original_filename), el("span", { class: "file-kind" }, dataset.dataset_type.replaceAll("_", " "))), download),
      el("div", { class: "file-details" }, el("span", {}, fileSize(file.byte_size)), el("span", {}, dataset.name), el("span", {}, dateLabel(dataset.created_at))),
      el("details", {}, el("summary", {}, "File integrity"), el("code", {}, `SHA-256 ${file.content_hash}`)));
  }));
  content.replaceChildren(el("div", { class: "section-header" }, el("h3", {}, `Files for revision ${state.revision.label}`), el("span", { class: "small-muted" }, `${cards.length} file${cards.length === 1 ? "" : "s"}`)), ...cards);
  if (state.item.kind === "assembly" || datasets.some(dataset => dataset.dataset_type === "native_cad")) {
    content.append(el("p", { class: "small-muted" }, "Downloads contain individual files. Use FreeCAD to retrieve a complete assembly with its linked components."));
  }
}
async function downloadFile(file, control) {
  control.disabled = true; control.textContent = "Downloading…";
  try {
    const blob = await request(`/files/${encodeURIComponent(file.id)}`, { binary: true });
    if (!state.user) return;
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: file.original_filename.replace(/[\\/]/g, "_"), hidden: true });
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) { if (error.name !== "AbortError") toast(error.message || "Download failed."); }
  finally { control.disabled = false; control.textContent = "Download ↓"; }
}
function renderWhereUsed(content, lines) {
  if (!lines.length) { content.replaceChildren(empty("No parent assemblies found", "No accessible stored BOM currently references any revision of this item.", "assembly")); return; }
  const rows = lines.map(line => [button(line.parent_item_number, () => navigate(line.parent_item_id, line.parent_revision_id), { class: "text-button number" }),
    line.parent_item_name, `Rev ${line.parent_revision_label}`, line.quantity]);
  content.replaceChildren(el("div", { class: "section-header" }, el("h3", {}, "Parent assemblies")),
    el("p", { class: "small-muted" }, "Shows accessible parent BOMs referencing any revision of this item."),
    dataTable(["Assembly", "Name", "Parent revision", "Quantity"], rows, "", "Where this item is used"));
}

management = managementUI({state, request, api, el, button, dataTable, dateLabel, toast, navigate, resetSession, loadProjects, signal:()=>session.signal});
for (const page of ["users", "project-settings", "checkouts", "activity", "account"]) document.querySelector(`#nav-${page}`).addEventListener("click",()=>setPage(page));
renderEmptyDetail();
fetch("/health", { cache: "no-store" }).then(response => {
  if (!response.ok) throw new Error();
  $("#server-status").replaceChildren(el("span", { class: "status-dot" }), "ForgePDM server online");
}).catch(() => { $("#server-status").textContent = "Server unavailable. Check your connection."; });
