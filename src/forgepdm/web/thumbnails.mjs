// One authorized exact-snapshot image at a time; no persistent image/token cache.
export function thumbnailViewer({api, el}) {
  let epoch = 0, controller, url;
  function reset() {
    epoch++;
    controller?.abort();
    if (url) URL.revokeObjectURL(url);
    url = null;
  }
  function render(host, datasets, label) {
    reset();
    const choices = datasets.filter(d => d.dataset_type === "native_cad")
      .flatMap(dataset => dataset.files.map(file => ({dataset, file})))
      .sort((a,b) => b.dataset.created_at.localeCompare(a.dataset.created_at) || b.dataset.id.localeCompare(a.dataset.id) || b.file.id.localeCompare(a.file.id));
    const image = el("div", {class:"thumbnail-image", role:"status"}, "No preview available");
    const picker = el("select", {"aria-label":"CAD snapshot for preview", onChange:load},
      ...choices.map(({dataset,file}, index) => el("option", {value:String(index)}, `${new Date(dataset.created_at).toLocaleString()} · ${file.original_filename}`)));
    host.replaceChildren(el("div", {class:"section-header"}, el("h3", {}, "Isometric preview")),
      ...(choices.length ? [picker] : []), image);
    async function load() {
      reset();
      const current = epoch, choice = choices[Number(picker.value)];
      if (!choice) { image.replaceChildren("No preview available"); return; }
      controller = new AbortController();
      const active = controller;
      const timer = setTimeout(() => active.abort(), 10000);
      image.replaceChildren("Loading preview…");
      try {
        const blob = await api.thumbnail(choice.file, active.signal);
        if (current !== epoch || !host.isConnected) return;
        if (!blob) { image.replaceChildren("No preview available"); return; }
        url = URL.createObjectURL(blob);
        image.replaceChildren(el("img", {src:url, alt:`${label}, isometric view of the selected uploaded CAD snapshot`, width:240, height:240,
          onError:() => { if (current === epoch) image.replaceChildren("Preview unavailable"); }}));
      } catch {
        if (current === epoch && host.isConnected) image.replaceChildren("Preview unavailable");
      } finally { clearTimeout(timer); }
    }
    if (choices.length) load();
  }
  return {render, reset};
}
