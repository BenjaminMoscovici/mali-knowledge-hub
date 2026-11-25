"use strict";

function downloadFile(name, content, type) {
  const objectUrl = URL.createObjectURL(new Blob([content], {type}));
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
}

function action(label, listener) {
  const button = el("button", "sources-button", label);
  button.type = "button";
  button.addEventListener("click", listener);
  return button;
}

function csv(rows) {
  const columns = Object.keys(rows[0]);
  const cell = (value) => {
    if (value === null || value === undefined) return "";
    let text = String(value);
    if (typeof value === "string" && (/^[\s\u0000-\u001f]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text))) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  };
  return "\uFEFF" + [columns, ...rows.map((row) => columns.map((key) => row[key]))]
    .map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

function bars(canvas, rows, label, field) {
  const values = rows.map((r) => r[field]).filter(Number.isFinite);
  if (!values.length) return;
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const ctx = canvas.getContext("2d");
  const width = canvas.width, plotStart = 206, plotWidth = width - plotStart - 145;
  const x = (v) => plotStart + plotWidth * (v - min) / (max - min || 1);
  canvas.height = 42 + rows.length * 30;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, canvas.height);
  ctx.font = "15px system-ui";
  rows.forEach((r, i) => {
    const y = 20 + 30 * i, value = r[field];
    ctx.textAlign = "right";
    ctx.fillStyle = "#1c332f";
    ctx.fillText(String(r[label] ?? "—"), plotStart - 12, y + 9, plotStart - 18);
    if (Number.isFinite(value)) {
      ctx.fillStyle = value < 0 ? "#b06142" : "#30786e";
      ctx.fillRect(Math.min(x(0), x(value)), y - 5, Math.max(1, Math.abs(x(0) - x(value))), 17);
    }
    ctx.textAlign = "left";
    ctx.fillStyle = "#1c332f";
    ctx.fillText(Number.isFinite(value) ? value.toLocaleString() : "—", plotStart + plotWidth + 12, y + 9, 124);
  });
}

async function regionalMap(canvas, rows, figure, item) {
  const source = await json("/api/sources/" + encodeURIComponent(figure.map_source) + "/geometry");
  const boundary = item.data.input_releases?.find(input => input.source_id === figure.map_source)
    || (item.source_id === figure.map_source ? item : null);
  if (!boundary || source.release !== boundary.release || (boundary.fingerprint &&
      boundary.fingerprint !== source.fingerprint && !(source.compatible_fingerprints || []).includes(boundary.fingerprint))) {
    throw new Error("The mapped boundary release has changed.");
  }
  const entries = Object.entries(source.geometries);
  const polygons = entries.map(([id, g]) => [id, g.type === "Polygon" ? [g.coordinates] : g.coordinates]);
  const points = polygons.flatMap(([, rings]) => rings.flat(2));
  const lons = points.map((p) => p[0]), lats = points.map((p) => p[1]);
  const west = Math.min(...lons), east = Math.max(...lons), south = Math.min(...lats), north = Math.max(...lats);
  const mid = (north + south) * Math.PI / 360;
  const scale = Math.min(610 / ((east - west) * Math.cos(mid)), 400 / (north - south));
  const x = (lon) => 20 + (lon - west) * Math.cos(mid) * scale;
  const y = (lat) => 18 + (north - lat) * scale;
  const values = new Map(rows.map((r) => [r[figure.map_field || figure.label_field], r[figure.value_field]]));
  const valid = Array.from(values.values()).filter(Number.isFinite);
  const min = Math.min(...valid), max = Math.max(...valid);
  canvas.height = 466;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "white";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (const [id, shapes] of polygons) {
    ctx.beginPath();
    for (const rings of shapes) for (const ring of rings) {
      ring.forEach(([lon, lat], i) => i === 0 ? ctx.moveTo(x(lon), y(lat)) : ctx.lineTo(x(lon), y(lat)));
      ctx.closePath();
    }
    const v = values.get(id);
    ctx.fillStyle = Number.isFinite(v) ? `hsl(169, 42%, ${max === min ? 42 : 82 - 56 * (v - min) / (max - min)}%)` : "#e9ebea";
    ctx.fill("evenodd");
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#667b75";
    ctx.stroke();
  }
  ctx.fillStyle = "#263d37";
  ctx.font = "16px system-ui";
  ctx.fillText(`${figure.value_field} · ${min.toLocaleString()} – ${max.toLocaleString()}  |  Grey = no value`, 18, 450, canvas.width - 36);
}

function exhibit(figure, item) {
  const box = el("figure", "exhibit");
  const caption = el("figcaption", "", figure.title);
  const rows = item.data.rows;
  box.append(caption);
  if (figure.kind !== "table") {
    const canvas = el("canvas");
    canvas.width = 800;
    canvas.setAttribute("aria-label", figure.title);
    canvas.setAttribute("role", "img");
    box.append(canvas);
    if (figure.kind === "chart") bars(canvas, rows, figure.label_field, figure.value_field);
    if (figure.kind === "map") canvas.rendered = regionalMap(canvas, rows, figure, item).catch(() => {
      canvas.replaceWith(el("p", "evidence-meta", "The map could not load. The source values are listed below."));
    });
    const details = el("details");
    details.append(el("summary", "", "Data table"), dataTable(rows));
    box.append(details);
  } else {
    box.append(dataTable(rows));
  }
  box.append(el("p", "evidence-meta", [item.publisher, item.release, item.data.unit].filter(Boolean).join(" · ")));
  if (item.data.truncated) box.append(el("p", "evidence-meta", "Showing the first 30 result rows."));
  box.append(action("Download CSV", () => downloadFile(item.id + ".csv", csv(rows), "text/csv;charset=utf-8")));
  return box;
}

async function downloadReport(turn, body, evidence) {
  await Promise.all(Array.from(body.querySelectorAll("canvas"), (canvas) => canvas.rendered));
  const report = document.implementation.createHTMLDocument("Mali Knowledge Hub research brief");
  const charset = report.createElement("meta");
  charset.setAttribute("charset", "utf-8");
  report.head.prepend(charset);
  const style = report.createElement("style");
  style.textContent = "body{max-width:850px;margin:3em auto;padding:0 2em;font:16px/1.55 Georgia,serif;color:#18332e}h1,h2,h3,figcaption{font-family:system-ui,sans-serif}a{color:#12645c}table{border-collapse:collapse;font-size:13px}td,th{padding:5px;border-bottom:1px solid #cfded9;text-align:left}figure{margin:1em 0}img{max-width:100%}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}section,figure{break-inside:avoid}@media print{body{margin:0;max-width:none}details{display:block}}";
  report.head.append(style);
  const title = body.querySelector("h2")?.textContent || turn.prompt || "Mali Knowledge Hub research brief";
  report.title = title;
  report.body.append(el("p", "", "Mali Knowledge Hub · Research brief"));
  if (!body.querySelector("h2")) report.body.append(el("h1", "", title));
  const copy = body.cloneNode(true);
  copy.querySelectorAll(".citation").forEach((button) => {
    const num = button.textContent;
    const anchor = document.createElement("a");
    anchor.textContent = "[" + num + "]";
    anchor.href = "#source-" + num;
    button.replaceWith(anchor);
  });
  copy.querySelectorAll("canvas").forEach((canvas, index) => {
    const img = document.createElement("img");
    img.alt = canvas.getAttribute("aria-label");
    img.src = body.querySelectorAll("canvas")[index].toDataURL();
    canvas.replaceWith(img);
  });
  copy.querySelectorAll("button").forEach((button) => button.remove());
  copy.querySelectorAll("details").forEach((detail) => { detail.open = true; });
  report.body.append(copy);
  if (evidence.length) report.body.append(el("h2", "", "Sources and calculations"));
  evidence.forEach((item, index) => {
    const card = evidenceCard(item, index + 1);
    card.id = "source-" + (index + 1);
    card.querySelectorAll("button").forEach((button) => button.remove());
    card.querySelectorAll("details").forEach((detail) => { detail.open = true; });
    report.body.append(card);
  });
  if (turn.partial) report.body.append(el("p", "", "Partial investigation"));
  downloadFile("MKH-research-brief.html", "<!doctype html>\n" + report.documentElement.outerHTML, "text/html;charset=utf-8");
}
