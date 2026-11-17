// One session per page; credentials and bearer tokens never enter browser storage.
export class APIError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
export class API {
  constructor() { this.language = "en"; this.token = null; this.onExpired = () => {}; }
  async request(path, options = {}) {
    const { method = "GET", body, signal, binary = false } = options;
    if (method === "GET" && (/^\/items(?:\?|$)/.test(path) || path.endsWith("/bom-report"))) path += `${path.includes("?") ? "&" : "?"}language=${encodeURIComponent(this.language)}`;
    if (method === "POST" && path === "/items" && body && !body.source_language) body.source_language = this.language;
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
  async thumbnail(file, signal) {
    const token = this.token;
    if (!token) return null;
    const response = await fetch(`/api/v1/files/${encodeURIComponent(file.id)}/thumbnail`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "image/png" },
      signal, cache: "no-store", credentials: "omit", redirect: "error"
    });
    if (response.status === 404) return null;
    if (response.status === 401 && token === this.token) this.onExpired();
    if (!response.ok) throw new APIError("Preview unavailable", response.status);
    return validatedThumbnail(response, file.content_hash);
  }
}

export async function validatedThumbnail(response, sourceHash) {
  const max = 1024 * 1024;
  if (response.headers.get("Content-Type")?.split(";")[0] !== "image/png" ||
      response.headers.get("X-ForgePDM-Source-Hash") !== sourceHash ||
      Number(response.headers.get("Content-Length")) > max) throw new Error("Invalid preview identity or size");
  const reader = response.body.getReader(), chunks = [];
  let length = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      length += value.length;
      if (length > max) { await reader.cancel(); throw new Error("Preview is too large"); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  const view = new DataView(bytes.buffer);
  if (length < 24 || ![137,80,78,71,13,10,26,10].every((byte, index) => bytes[index] === byte) ||
      view.getUint32(16) < 1 || view.getUint32(16) > 512 || view.getUint32(20) < 1 || view.getUint32(20) > 512)
    throw new Error("Invalid preview image");
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2,"0")).join("");
  if (digest !== response.headers.get("X-Content-SHA256")) throw new Error("Preview checksum mismatch");
  return new Blob([bytes], {type: "image/png"});
}
