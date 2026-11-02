// One session per page; credentials and bearer tokens never enter browser storage.
export class APIError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
export class API {
  constructor() { this.token = null; this.onExpired = () => {}; }
  async request(path, options = {}) {
    const { method = "GET", body, signal, binary = false } = options;
    const token = this.token;
    const headers = { Accept: binary ? "application/octet-stream" : "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body) headers["Content-Type"] = "application/json";
    const response = await fetch(`/api/v1${path}`, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
      signal, cache: "no-store", credentials: "omit", redirect: "error"
    });
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch { /* No server detail. */ }
      if (response.status === 401 && token && token === this.token) this.onExpired();
      const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(issue=>`${issue.loc?.at(-1) || "Input"}: ${issue.msg}`).join("; ") :
        response.status === 404 ? "This record is unavailable or you do not have access." :
        response.status === 401 ? "Your session has expired. Please sign in again." :
        "The request could not be completed. Please try again.";
      throw new APIError(message, response.status);
    }
    if (binary) return response.blob();
    return response.status === 204 ? null : response.json();
  }
  async allPages(path, signal) {
    const rows = [];
    let offset = 0;
    while (true) {
      const separator = path.includes("?") ? "&" : "?";
      const page = await this.request(`${path}${separator}limit=100&offset=${offset}`, { signal });
      rows.push(...page.items);
      if (!page.has_more) return rows;
      offset += 100;
    }
  }
}
