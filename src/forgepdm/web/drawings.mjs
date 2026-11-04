// Authenticated PDF previews use short-lived Blob URLs, never bearer tokens in URLs.
export function drawingViewer({ state, request, el, button, dateLabel }) {
  let generation = 0, previewVersion = 0;
  const urls = new Set();
  const frames = new Set();
  function reset() {
    generation++; previewVersion++;
    for (const frame of frames) { frame.removeAttribute("src"); frame.remove(); }
    frames.clear();
    for (const url of urls) URL.revokeObjectURL(url);
    urls.clear();
  }
  async function pdfBytes(page) {
    const blob = await request(`/files/${encodeURIComponent(page.file_id)}`, { binary: true });
    if (blob.size !== page.byte_size || await blob.slice(0, 5).text() !== "%PDF-") throw new Error("The downloaded file does not match the published PDF.");
    return new Blob([blob], { type: "application/pdf" });
  }
  function render(content, publications, refresh) {
    reset();
    const header = el("div", { class: "section-header" }, el("h3", {}, "Published drawings"),
      button("Refresh drawings", () => { reset(); refresh(); }, { class: "secondary" }));
    if (!publications.length) {
      content.replaceChildren(header, el("div", { class: "info-card" },
        el("p", {}, "No drawing PDFs have been published for this revision."),
        el("p", { class: "small-muted" }, "Use Publish Drawing PDFs… in FreeCAD from a saved/uploaded Working revision with your checkout.")));
      return;
    }
    const selector = el("select", { id: "drawing-publication", "aria-label": "Drawing publication" },
      ...publications.map((publication, index) => el("option", { value: publication.id },
        `Publication ${publications.length - index} · ${dateLabel(publication.created_at)} · ${publication.pages.length} page(s)${index === 0 ? " · newest" : ""}`)));
    const body = el("div", { class: "drawing-publication" });
    const choose = () => {
      reset();
      const publication = publications.find(row => row.id === selector.value);
      const revisionId = state.revision.id;
      const meta = el("div", { class: "info-card drawing-source" },
        el("p", {}, `Published ${dateLabel(publication.created_at)} by ${publication.published_by || "a project member"}.`),
        el("p", { class: "small-muted" }, `Source CAD uploaded ${dateLabel(publication.source_created_at)}.`),
        el("details", {}, el("summary", {}, "Exact source"), el("p", {}, `Native dataset: ${publication.source_dataset_id}`), el("p", {}, `Native file: ${publication.source_file_id}`), el("code", {}, `SHA-256 ${publication.source_content_hash}`)));
      const status = publication.newer_snapshot_available
        ? el("p", { class: "revision-note", role: "status" }, "Newer CAD snapshot available. These PDFs represent the recorded source snapshot.")
        : el("p", { class: "small-muted" }, "These PDFs match the latest uploaded CAD snapshot at the last refresh.");
      const pagePicker = el("select", { id: "drawing-page", "aria-label": "Drawing page" },
        ...publication.pages.map(page => el("option", { value: page.page_name }, `${page.position}. ${page.page_label}`)));
      const preview = el("div", { class: "pdf-preview" });
      const message = el("p", { class: "small-muted", role: "status" }, "Select a page and click Preview PDF.");
      let currentPreviewURL;
      const valid = gen => gen === generation && state.user && state.page === "catalog" && state.tab === "drawings" && state.revision?.id === revisionId && content.isConnected;
      const previewButton = button("Preview PDF", async () => {
        const gen = generation, version = ++previewVersion;
        const page = publication.pages.find(row => row.page_name === pagePicker.value);
        previewButton.disabled = true; message.textContent = "Loading PDF…";
        try {
          const blob = await pdfBytes(page);
          if (!valid(gen) || version !== previewVersion) return;
          if (currentPreviewURL) { URL.revokeObjectURL(currentPreviewURL); urls.delete(currentPreviewURL); }
          for (const frame of frames) frame.remove();
          frames.clear();
          currentPreviewURL = URL.createObjectURL(blob); urls.add(currentPreviewURL);
          const frame = el("iframe", { class: "pdf-frame", title: `PDF preview: ${page.page_label}`, src: currentPreviewURL, referrerpolicy: "no-referrer" });
          frames.add(frame); preview.replaceChildren(frame);
          frame.scrollIntoView({ behavior: "smooth", block: "nearest" });
          message.textContent = "Use Download PDF if your browser cannot display the preview.";
        } catch (error) {
          if (valid(gen) && version === previewVersion && error.name !== "AbortError") message.textContent = error.message || "PDF preview failed.";
        } finally { if (valid(gen) && version === previewVersion) previewButton.disabled = false; }
      }, { class: "secondary" });
      const download = button("Download PDF", async () => {
        const gen = generation;
        const page = publication.pages.find(row => row.page_name === pagePicker.value);
        download.disabled = true;
        try {
          const blob = await pdfBytes(page);
          if (!valid(gen)) return;
          const url = URL.createObjectURL(blob); urls.add(url);
          const link = el("a", { href: url, download: page.filename.replace(/[\\/]/g, "_"), hidden: true });
          document.body.append(link); link.click(); link.remove();
          setTimeout(() => { URL.revokeObjectURL(url); urls.delete(url); }, 60000);
        } catch (error) { if (valid(gen) && error.name !== "AbortError") message.textContent = error.message || "PDF download failed."; }
        finally { if (valid(gen)) download.disabled = false; }
      }, { class: "primary" });
      pagePicker.addEventListener("change", () => {
        previewVersion++;
        for (const frame of frames) frame.remove(); frames.clear();
        if (currentPreviewURL) { URL.revokeObjectURL(currentPreviewURL); urls.delete(currentPreviewURL); currentPreviewURL = null; }
        preview.replaceChildren(); previewButton.disabled = false;
        message.textContent = "Click Preview PDF for the selected page.";
      });
      body.replaceChildren(meta, status, el("div", { class: "drawing-controls" },
        el("label", { for: "drawing-page" }, "Page"), pagePicker, previewButton, download), message, preview);
    };
    selector.addEventListener("change", choose);
    content.replaceChildren(header, el("label", { for: "drawing-publication", class: "section-caption" }, "Publication history"), selector, body);
    choose();
  }
  return { render, reset };
}
