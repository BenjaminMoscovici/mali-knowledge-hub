"use strict";

async function openSourceReview() {
  openDrawer("Source review");
  const inventory = await json("/api/admin/sources");
  if (drawer.classList.contains("hidden")) return;
  const notice = el("p", "evidence-meta");
  notice.setAttribute("role", "status");
  const fields = new Map();
  const form = el("form", "notes-form");
  const file = el("input");
  file.type = "file";
  file.accept = ".csv,.tsv,.xlsx,.pdf,.txt,.md,.json";
  const fileLabel = el("label", "", "Public source file");
  fileLabel.append(file);
  form.append(fileLabel);

  for (const [name, title] of Object.entries({
    title: "Title", id: "Source ID", publisher: "Publisher", url: "Original HTTPS URL",
    release: "Version or release date", period: "Period covered", geography: "Geographic coverage",
    license: "Licence or redistribution terms", description: "What the source contains", topics: "Search topics",
    limitations: "Limitations and interpretation", update_policy: "Update frequency or policy"
  })) {
    const label = el("label", "", title);
    const input = el(["limitations","description"].includes(name) ? "textarea" : "input");
    if (input.tagName === "TEXTAREA") input.rows = 2;
    label.append(input);
    form.append(label);
    fields.set(name, input);
  }
  const options = el("details");
  options.append(el("summary", "", "Workbook sheet and column types"));
  for (const [name, title] of [["sheet","Workbook sheet"],["column_types","Column type overrides (JSON)"]]) {
    const label = el("label", "", title);
    const input = el("input");
    label.append(input); options.append(label); fields.set(name, input);
  }
  form.append(options);
  const scopeOptions = el("details");
  scopeOptions.append(el("summary", "", "Scope for cross-source analysis"));
  const scopeFields = new Map();
  for (const [name, title] of Object.entries({
    geographic_frame: "Geographic framework and boundary version", grain: "What one record represents",
    measure: "Indicator and definition", units: "Units and denominator", basis: "Observation method or evidence type"
  })) {
    const label = el("label", "", title);
    const input = el("input");
    input.maxLength = 240;
    scopeFields.set(name, input);
    label.append(input);
    scopeOptions.append(label);
  }
  const windows = el("textarea");
  windows.rows = 2;
  const windowLabel = el("label", "", "Coverage periods, one YYYY-MM-DD / YYYY-MM-DD pair per line");
  windowLabel.append(windows);
  scopeOptions.append(windowLabel);
  form.append(scopeOptions);
  const report = el("div", "review-report");
  async function processFile(op) {
    notice.textContent = "";
    try {
      const chosen = file.files[0];
      if (!chosen || chosen.size > 1500000) throw new Error("Choose a public file of up to 1.5 MB.");
      const content = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = () => reject(new Error("The file could not be read."));
        reader.readAsDataURL(chosen);
      });
      const metadata = Object.fromEntries([...fields].map(([name, input]) => [name, input.value]));
      metadata.comparison_scope = Object.fromEntries([...scopeFields]
        .map(([name, input]) => [name, input.value.trim()]).filter(([, value]) => value));
      if (windows.value.trim()) metadata.comparison_scope.windows = windows.value.trim()
        .split(/\n/).map(line => line.split("/").map(date => date.trim()));
      metadata.column_types = JSON.parse(metadata.column_types || "{}");
      const data = await json("/api/admin/sources", {operation:op, filename:chosen.name, content, metadata});
      fields.get("id").value = data.id; fields.get("title").value = data.title;
      for (const [key, value] of Object.entries(data.suggestions || {})) fields.get(key).value = value;
      if (op === "draft") { await openSourceReview(); return; }
      const identical = inventory.versions.filter(v => v.sha === data.upload_sha256);
      report.replaceChildren(reviewDetail(data));
      notice.textContent = identical.length ? "This file matches a saved version. Check its version and metadata." :
        op === "suggest" ? "Review the proposed metadata before saving." : "File inspected. Review the source details.";
    } catch (err) { notice.textContent = err.message; }
  }
  for (const [label, op] of [["Inspect file","inspect"],["Suggest metadata with AI","suggest"],["Save draft","draft"]]) {
    form.append(action(label, () => processFile(op)));
  }
  form.addEventListener("submit", event => event.preventDefault());

  const manage = el("section", "notes-form");
  const source = el("select"); source.setAttribute("aria-label", "Source to manage");
  for (const key of [...new Set([...inventory.bundled, ...inventory.versions.map(v => v.source_id)])].sort())
    source.add(new Option(key,key));
  const versions = el("select"); versions.setAttribute("aria-label", "Version to review");
  const details = el("div"); const status = el("p", "evidence-meta");
  const publish = action("Publish reviewed version", () => change("published"));
  const suspend = action("Suspend source", () => change("suspended"));
  const withdraw = action("Withdraw source", () => change("withdrawn"));
  const restore = action("Restore bundled version", () => change("bundled"));
  async function showVersion() {
    publish.disabled = true; details.replaceChildren();
    const id = versions.value;
    if (!id) return;
    try {
      const metadata = await json("/api/admin/sources?version=" + encodeURIComponent(id));
      if (versions.value === id) { details.append(reviewDetail(metadata)); publish.disabled = false; }
    } catch (err) { notice.textContent = err.message; }
  }
  function showSourceState() {
    const key = source.value, state = inventory.states[key];
    status.textContent = "Current status · " + (state?.status || (inventory.bundled.includes(key) ? "bundled" : "draft only"));
    versions.replaceChildren();
    for (const v of inventory.versions.filter(v => v.source_id === key)) {
      versions.add(new Option(v.release + (v.id === state?.version_id ? " · published" : ""), v.id));
    }
    versions.hidden = !versions.length;
    restore.disabled = !inventory.bundled.includes(key) || !state || state.status === "bundled";
    suspend.disabled = !state && !inventory.bundled.includes(key) || state?.status === "suspended";
    withdraw.disabled = !state && !inventory.bundled.includes(key) || state?.status === "withdrawn";
    showVersion();
  }
  async function change(next) {
    try {
      await json("/api/admin/sources", {operation:"change", source_id:source.value, status:next,
        version_id:next === "published" ? versions.value : null, expected:inventory.states[source.value]?.revision || null});
      await openSourceReview();
    } catch (err) { notice.textContent = err.message; }
  }
  source.addEventListener("change", showSourceState);
  versions.addEventListener("change", showVersion);
  manage.append(el("h3", "", "Releases"), source, status, versions, details, publish, suspend, withdraw, restore);
  const upload = el("details");
  upload.append(el("summary", "", "Submit a public source"), form, report);
  drawerBody.append(notice, upload, manage);
  showSourceState();
}

function reviewDetail(source) {
  const box = el("article", "evidence-item");
  box.append(el("h3", "", source.title),
    el("p", "evidence-meta", [source.publisher, source.release, source.geography, source.period].filter(Boolean).join(" · ")),
    el("p", "", source.description), el("p", "", (source.limitations || []).join(" ")));
  if (source.samples) box.append(el("p", "", source.row_count + " rows"), dataTable(source.samples));
  if (source.excerpt) box.append(el("p", "", source.page_count + " text pages"), el("blockquote", "", source.excerpt));
  if (source.series) box.append(el("p", "", Object.keys(source.series).length + " registered series"));
  const upstream = link(source.url, "Open original source ↗");
  if (upstream) box.append(upstream);
  return box;
}
byId("source-review").addEventListener("click", () => openSourceReview().catch(f => {
  drawerBody.replaceChildren(el("p", "", f.message));
}));
