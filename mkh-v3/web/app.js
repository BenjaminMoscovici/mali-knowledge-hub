"use strict";

const byId = (id) => document.getElementById(id);
const promptBox = byId("prompt");
const statusLine = byId("preview-status");
const drawer = byId("evidence-drawer");
const drawerBody = byId("drawer-body");
const messages = byId("messages");
const dialog = byId("auth-dialog");
let session = null;
let conversationId = null;
let workingInstructions = "";
let currentRequirements = {};
let earlierBefore = null;
let active = null;
let stopping = Promise.resolve();
const conversationKey = "mkh-v31-current-chat";
let viewRevision = 0;
const pendingJobKey = "mkh-v31-pending-research";
let authMode = "sign-in";
let opener = null;

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

async function request(path, options = {}) {
  const response = await fetch(path, {signal: AbortSignal.timeout(path === "/api/session" ? 65000 : 22000), ...options});
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    const error = new Error(failure.error || "The V3.1 preview could not complete this request.");
    error.status = response.status;
    throw error;
  }
  return response;
}

async function json(path, body) {
  const options = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  };
  return (await request(path, options)).json();
}

function updateComposer(status = "") {
  const needsSignIn = session?.auth_enabled && !session.authenticated;
  byId("composer-sign-in").classList.toggle("hidden", !needsSignIn);
  byId("composer-sign-in").disabled = Boolean(active);
  byId("profile-button").disabled = Boolean(active);
  byId("send-button").disabled = Boolean(active) || !promptBox.value.trim();
  byId("cancel-button").classList.toggle("hidden", !active);
  byId("new-chat").title = active ? "Stop this assignment and start a new chat" : "Start a new chat";
  byId("working-notes").disabled = Boolean(active);
  byId("personal-memory").disabled = Boolean(active);

  statusLine.textContent = status || (
    !session ? "Checking the V3.1 preview session…" :
      !session.model_configured ? "V3.1 preview · Source browsing is available. Model access is being configured." :
        !session.authenticated ? "Guest chat · Temporary conversation" :
        "V3.1 preview · Saved to your MKH account."
  );
}

function openDrawer(title) {
  if (drawer.classList.contains("hidden")) opener = document.activeElement;
  drawer.querySelector("h2").textContent = title;
  drawer.classList.remove("hidden");
  byId("drawer-scrim").classList.remove("hidden");
  drawerBody.replaceChildren();
  byId("drawer-close").focus();
}

function closeDrawer() {
  drawer.classList.add("hidden");
  byId("drawer-scrim").classList.add("hidden");
  if (opener?.isConnected) opener.focus();
  opener = null;
}

function link(url, label) {
  try {
    const target = new URL(url);
    if (target.protocol !== "https:" || target.username || target.password) return null;
    const anchor = el("a", "evidence-link", label);
    anchor.href = target.href;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    return anchor;
  } catch {
    return null;
  }
}

function dataTable(rows) {
  if (!rows?.length) return el("p", "evidence-meta", "No rows were returned.");
  const wrapper = el("div", "result-table");
  const table = el("table");
  const headings = Object.keys(rows[0]);
  const head = el("tr");
  headings.forEach((name) => head.append(el("th", "", name)));
  const thead = el("thead");
  thead.append(head);
  table.append(thead);
  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    headings.forEach((name) => tr.append(el("td", "", row[name] ?? "—")));
    body.append(tr);
  }
  table.append(body);
  wrapper.append(table);
  return wrapper;
}

function evidenceCard(item, number) {
  const card = el("article", "evidence-item");
  if (number) card.dataset.citation = number;
  const title = item.origin === "public_web" ? "External web · " + item.title : item.title;
  card.append(el("h3", "", number ? `${number}. ${title}` : title));
  card.append(el("p", "evidence-meta", [item.publisher, item.release, item.locator, item.source_period]
    .filter(Boolean).join(" · ")));
  if (item.license) {
    const attribution = el("p", "evidence-meta", item.license);
    const terms = link(item.reuse_url, "Reuse terms ↗");
    if (terms) attribution.append(" ", terms);
    card.append(attribution);
  }
  const data = item.data || {};
  if (data.text) card.append(el("blockquote", "", data.text));
  if (data.sql) {
    const operations = el("details");
    operations.append(el("summary", "", "Calculation and inputs"));
    operations.append(el("pre", "calculation", data.sql));
    for (const release of data.input_releases || []) {
      operations.append(el("p", "evidence-meta", `${release.table} · ${release.release} · ${release.period}`));
    }
    for (const row of data.input_records || []) {
      operations.append(el("p", "evidence-meta", row.locator));
    }
    card.append(operations);
  }
  if (data.unit || data.provider_last_updated) {
    card.append(el("p", "evidence-meta", [data.label, data.unit, data.provider_last_updated]
      .filter(Boolean).join(" · ")));
  }
  if (data.relationship) {
    const rel = data.relationship;
    card.append(el("p", "evidence-meta", rel.entity + " · " + rel.method + " · " + rel.matched_pairs + " matched pairs"));
    if (Number.isInteger(rel.left_unmatched_rows)) {
      card.append(el("p", "evidence-meta", "Input rows without a match · " + rel.left + " " + rel.left_unmatched_rows
        + " · " + rel.right + " " + rel.right_unmatched_rows));
    }
  }
  if (data.parent_evidence) {
    const parent = data.parent_evidence;
    const view = el("details");
    view.append(el("summary", "", "Input to this calculation"), el("p", "", parent.locator + " · " + parent.release));
    if (parent.data.sql) view.append(el("pre", "calculation", parent.data.sql));
    view.append(dataTable(parent.data.rows));
    const original = link(parent.url, "Open input source ↗");
    if (original) view.append(original);
    card.append(view);
  }
  if (data.rows) {
    card.append(dataTable(data.rows));
    if (data.rows.length) card.append(action("Download CSV", () =>
      downloadFile(item.id + ".csv", csv(data.rows), "text/csv;charset=utf-8")));
  }
  if (data.truncated) card.append(el("p", "evidence-meta", "Showing the first 30 query rows."));
  if (!data.rows && !data.text && item.kind === "source_record") card.append(dataTable([data]));
  const original = link(item.url, "Open original source ↗");
  if (original) card.append(original);
  return card;
}

function showEvidence(evidence, selection) {
  openDrawer("Sources");
  evidence.forEach((item, index) => drawerBody.append(evidenceCard(item, index + 1)));
  if (selection) {
    const target = drawerBody.querySelector(`[data-citation="${selection}"]`);
    if (target) {
      target.classList.add("selected");
      target.scrollIntoView({block: "nearest"});
    }
  }
}

async function showCatalogue() {
  openDrawer("What the Hub knows");
  const form = el("form", "catalogue-search");
  const input = el("input");
  input.type = "search";
  input.placeholder = "Search approved sources";
  input.setAttribute("aria-label", "Search approved sources");
  const submit = el("button", "sources-button", "Search");
  form.append(input, submit);
  const results = el("div");
  drawerBody.append(form, results);
  let searchVersion = 0;
  async function load() {
    const version = ++searchVersion;
    results.replaceChildren(el("p", "evidence-meta", "Loading approved sources…"));
    try {
      const {sources, catalogue_total, matching_total} = await json("/api/sources?q=" + encodeURIComponent(input.value) + "&view=summary");
      if (version !== searchVersion) return;
      results.replaceChildren(el("p", "evidence-meta", matching_total + " matching · " + catalogue_total + " published"));
      if (!sources.length) results.append(el("p", "evidence-meta", "No matching published sources."));
      for (const item of sources) {
        const card = el("article", "evidence-item");
        const detail = el("button", "source-title", item.title);
        detail.type = "button";
        detail.addEventListener("click", () => {
          const position = drawerBody.scrollTop;
          showSource(item.id, () => {
            openDrawer("What the Hub knows");
            drawerBody.append(form, results);
            detail.focus({preventScroll: true});
            drawerBody.scrollTop = position;
          });
        });
        card.append(detail, el("p", "evidence-meta", [item.publisher, item.period].filter(Boolean).join(" · ")),
          el("p", "source-description", item.description));
        results.append(card);
      }
    } catch (failure) {
      if (version === searchVersion) results.replaceChildren(el("p", "evidence-meta", failure.message));
    }
  }
  form.addEventListener("submit", (event) => { event.preventDefault(); load(); });
  await load();
}

async function showSource(id, returnToList) {
  openDrawer("Source details");
  try {
    const info = await json("/api/sources/" + encodeURIComponent(id));
    if (drawer.classList.contains("hidden")) return;
    drawer.querySelector("h2").textContent = info.title;
    const back = el("button", "sources-button", "Back to sources");
    back.addEventListener("click", returnToList);
    drawerBody.append(back, el("p", "source-description", info.description),
      el("p", "evidence-meta", [info.publisher, info.release, info.geography, info.period, info.license]
        .filter(Boolean).join(" · ")));
    const list = el("ul", "source-limits");
    for (const line of info.limitations || []) list.append(el("li", "", line));
    drawerBody.append(list);
    const original = link(info.url, "Open original publication ↗");
    if (original) drawerBody.append(original);
    for (const reference of info.related_references || []) {
      const related = link(reference.url, reference.title);
      if (related) drawerBody.append(related, el("p", "evidence-meta", reference.scope));
    }
    for (const item of info.evidence || []) drawerBody.append(evidenceCard(item));
    if (info.samples) {
      drawerBody.append(el("h3", "", `Sample records · ${info.row_count} in release`), dataTable(info.samples));
    }
    if (info.series) {
      for (const [code, series] of Object.entries(info.series)) {
        const show = el("button", "sources-button series-button", series.label + " · latest years");
        const result = el("div");
        show.addEventListener("click", async () => {
          show.disabled = true;
          result.replaceChildren(el("p", "evidence-meta", "Checking approved live API…"));
          try {
            const end = new Date().getFullYear() - 1;
            const data = await json(`/api/sources/${encodeURIComponent(id)}?series=${encodeURIComponent(code)}&start_year=${end - 4}&end_year=${end}`);
            result.replaceChildren(...data.evidence.map((item) => evidenceCard(item)));
          } catch (failure) {
            result.replaceChildren(el("p", "evidence-meta", failure.message));
          } finally {
            show.disabled = false;
          }
        });
        drawerBody.append(show, result);
      }
    }
  } catch (failure) {
    drawerBody.replaceChildren(el("p", "evidence-meta", failure.message));
  }
}

function inline(node, line, evidence) {
  const citations = new Map(evidence.map((item, index) => [item.id, index + 1]));
  for (const part of line.split(/(\[\[E-[a-f0-9]{16}\]\]|\*\*[^*]+\*\*)/)) {
    if (part.startsWith("[[E-") && citations.has(part.slice(2, -2))) {
      const number = citations.get(part.slice(2, -2));
      const marker = el("button", "citation", number);
      marker.type = "button";
      marker.setAttribute("aria-label", "Inspect source " + number);
      marker.addEventListener("click", () => showEvidence(evidence, number));
      node.append(marker);
    } else if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      node.append(el("strong", "", part.slice(2, -2)));
    } else {
      node.append(document.createTextNode(part));
    }
  }
}

function renderAnswer(container, text, evidence) {
  const lines = text.split("\n");
  let list = null;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (line.startsWith("```")) {
      const code = [];
      while (index + 1 < lines.length && !lines[index + 1].trimStart().startsWith("```")) code.push(lines[++index]);
      if (index + 1 < lines.length) index++;
      const block = el("pre", "calculation");
      block.append(el("code", "", code.join("\n")));
      container.append(block);
      list = null;
      continue;
    }
    if (!line) {
      list = null;
      continue;
    }
    if (line.startsWith("|") && /^\|[ |:\-]+\|$/.test(lines[index + 1]?.trim() || "")) {
      const split = (raw) => raw.trim().slice(1, -1).split("|").map((cell) => cell.trim());
      const headers = split(line);
      const wrapper = el("div", "result-table");
      const table = el("table");
      const head = el("tr");
      headers.forEach((value) => {
        const cell = el("th");
        inline(cell, value, evidence);
        head.append(cell);
      });
      const thead = el("thead");
      thead.append(head);
      table.append(thead);
      const tbody = el("tbody");
      index += 2;
      while (index < lines.length && /^\|.*\|$/.test(lines[index].trim())) {
        const row = el("tr");
        split(lines[index]).forEach((value) => {
          const cell = el("td");
          inline(cell, value, evidence);
          row.append(cell);
        });
        tbody.append(row);
        index += 1;
      }
      index -= 1;
      table.append(tbody);
      wrapper.append(table);
      container.append(wrapper);
      list = null;
      continue;
    }
    const bullet = line.match(/^(?:[-*]|\d+\.) (.+)$/);
    if (bullet) {
      if (!list) {
        list = el(/^\d/.test(line) ? "ol" : "ul");
        container.append(list);
      }
      const item = el("li");
      inline(item, bullet[1], evidence);
      list.append(item);
      continue;
    }
    list = null;
    const header = line.match(/^#{1,4} (.+)$/);
    const node = el(header ? "h2" : "p");
    inline(node, header ? header[1] : line, evidence);
    container.append(node);
  }
}

function scrollToLatest() {
  requestAnimationFrame(() => { byId("conversation-scroll").scrollTop = byId("conversation-scroll").scrollHeight; });
}

function appendUser(text, parent = messages) {
  byId("welcome").classList.add("hidden");
  const node = el("div", "message user");
  node.append(el("div", "user-bubble", text));
  parent.append(node);
  if (parent === messages) scrollToLatest();
  return node;
}

function researchActivity(steps) {
  const details = el("details", "research-activity");
  details.append(el("summary", "", "Research activity · " + steps.length + (steps.length === 1 ? " step" : " steps")));
  const list = el("ol");
  for (const step of steps) {
    const label = step.status === "completed" ? step.action : step.action + " (incomplete)";
    list.append(el("li", "", [label, step.detail].filter(Boolean).join(" · ")));
  }
  details.append(list);
  return details;
}

function showScopeReview(review) {
  openDrawer("Compare sources");
  drawerBody.append(el("p", "source-description", review.interpretation));
  const titles = new Map(review.sources.map((s) => [s.source_id, s.title]));
  if (review.outcome_alignment?.length) {
    const box = el("article", "evidence-item");
    box.append(el("h3", "", "Programme outcomes and available measures"));
    for (const check of review.outcome_alignment) {
      const names = check.sources_declaring_measure.map((key) => titles.get(key));
      box.append(el("p", "", check.outcome + " · " + (names.join(", ") || "No matching indicator declared in these sources.")));
    }
    drawerBody.append(box);
  }
  for (const pair of review.pairs) {
    const box = el("article", "evidence-item");
    box.append(el("h3", "", titles.get(pair.left) + " / " + titles.get(pair.right)),
      el("p", "", "Reporting periods · " + pair.period_relation),
      el("p", "", pair.registered_record_keys.length ? "Shared identifiers · " + pair.registered_record_keys.join(", ")
        : "No registered identifier links these releases."));
    if (pair.distinct_declarations.length) box.append(el("p", "", "Declared differences · "
      + pair.distinct_declarations.map((d) => d.replaceAll("_", " ")).join(", ")));
    if (pair.unspecified.length) box.append(el("p", "evidence-meta", "Undocumented for one or both sources · "
      + pair.unspecified.map((d) => d.replaceAll("_", " ")).join(", ")));
    drawerBody.append(box);
  }
  for (const source of review.sources) {
    const box = el("article", "evidence-item");
    box.append(el("h3", "", source.title), el("p", "", source.geography + " · " + source.period));
    for (const field of ["grain", "measure", "units", "basis"]) {
      if (source[field]) box.append(el("p", "evidence-meta", field + " · " + source[field]));
    }
    for (const selected of source.returned_labels || []) {
      const labels = Object.entries(selected.labels).map(([key, values]) => key + " · " + values.join(", "));
      box.append(el("p", "evidence-meta", labels.join(" / ")));
    }
    drawerBody.append(box);
  }
}

function appendAnswer(turn, parent = messages) {
  const evidence = turn.evidence || [];
  const message = el("div", "message assistant");
  const body = el("div", "assistant-turn");
  renderAnswer(body, turn.answer || turn.text, evidence);
  for (const figure of turn.artifacts || []) {
    const item = evidence.find((e) => e.id === figure.evidence_id);
    if (item?.data?.rows?.length) body.append(exhibit(figure, item));
  }
  message.append(body);
  if (turn.research_steps?.length) message.append(researchActivity(turn.research_steps));
  const footer = el("div", "message-footer");
  if (evidence.length) {
    const view = el("button", "sources-button", `View sources (${evidence.length})`);
    view.addEventListener("click", () => showEvidence(evidence));
    footer.append(view);
  }
  if (turn.scope_review?.pairs?.length) footer.append(action("Compare sources", () => showScopeReview(turn.scope_review)));
  footer.append(action("Download brief", () => downloadReport(turn, body, evidence)));
  if (evidence.length) footer.append(action("Evidence file", () => downloadFile("MKH-evidence.json",
    JSON.stringify({evidence, scope_review: turn.scope_review, exhibits: turn.artifacts || []}, null, 2), "application/json")));
  if (Number.isFinite(turn.usage?.estimated_model_usd)) {
    footer.append(el("span", "", "Est. model cost · $" + turn.usage.estimated_model_usd.toFixed(3)));
  }
  if (turn.usage?.retrieval_fallback) footer.append(el("span", "", "Used text search while semantic search was unavailable"));
  if (turn.partial || turn.tool_failures?.length) {
    footer.append(el("span", "", turn.partial ? "Research incomplete" : "Some research tools could not complete"));
  }
  message.append(footer);
  parent.append(message);
  if (parent === messages) scrollToLatest();
}

function reset() {
  viewRevision++;
  sessionStorage.removeItem(conversationKey);
  sessionStorage.removeItem(pendingJobKey);
  earlierBefore = null;
  byId("earlier-turns").classList.add("hidden");
  workingInstructions = "";
  currentRequirements = {};
  conversationId = null;
  messages.replaceChildren();
  byId("welcome").classList.remove("hidden");
  byId("topbar-title").textContent = "Mali Knowledge Hub";
  promptBox.value = "";
  updateComposer();
}

function showSavedTurns(value, parent) {
  earlierBefore = value.earlier_before;
  byId("earlier-turns").classList.toggle("hidden", !earlierBefore);
  for (const turn of value.turns) {
    appendUser(turn.prompt, parent);
    if (turn.answer) appendAnswer(turn, parent);
    if (turn.withdrawn) parent.append(el("p", "evidence-meta", "Earlier evidence is outside the current approved scope."));
  }
}

async function loadEarlier() {
  if (!conversationId || !earlierBefore) return;
  const id = conversationId;
  const button = byId("earlier-turns");
  button.disabled = true;
  try {
    const result = await json("/api/conversations/" + id + "?before=" + earlierBefore);
    if (id !== conversationId) return;
    const group = document.createDocumentFragment();
    showSavedTurns(result, group);
    const previous = messages.firstElementChild;
    messages.prepend(group);
    previous?.scrollIntoView({block: "start"});
  } catch (failure) { updateComposer(failure.message); }
  finally { button.disabled = false; }
}

async function recent() {
  const list = byId("thread-list");
  list.replaceChildren();
  if (!session?.authenticated) return;
  const viewingSession = session;
  const data = await json("/api/conversations");
  if (session !== viewingSession) return;
  for (const entry of data.conversations) {
    const row = el("div", "thread-row");
    const button = el("button", "thread-title", entry.title);
    button.addEventListener("click", async () => {
      if (active) return;
      try {
        const opening = ++viewRevision;
        const value = await json("/api/conversations/" + entry.id);
        if (session !== viewingSession || opening !== viewRevision || active) return;
        reset();
        conversationId = entry.id;
        sessionStorage.setItem(conversationKey, entry.id);
        workingInstructions = value.turns.at(-1)?.instructions || "";
        currentRequirements = value.turns.at(-1)?.requirements || {};
        byId("topbar-title").textContent = entry.title;
        showSavedTurns(value, messages);
        if (window.innerWidth <= 800) setSidebar(false);
      } catch (failure) {
        updateComposer(failure.message);
      }
    });
    row.append(button);
    list.append(row);
  }
}

async function refreshSession() {
  session = await json("/api/session");
  byId("personal-memory").classList.toggle("hidden", !session.authenticated);
  byId("source-review").classList.toggle("hidden", !session.source_editor);
  byId("profile-title").textContent = session.authenticated ? "Sign out" : "Sign in";
  byId("history-label").classList.toggle("hidden", !session.authenticated);
  updateComposer();
  recent().catch(() => {
    if (session?.authenticated) {
      byId("thread-list").textContent = "Saved chats could not be loaded.";
    }
  });
}

function authStatus(text) {
  const box = byId("auth-status");
  box.textContent = text;
  box.classList.toggle("hidden", !text);
}

function openSignIn(mode = "sign-in", message = "") {
  if (!session?.auth_enabled) {
    updateComposer("V3.1 sign-in is temporarily unavailable.");
    return;
  }
  authMode = mode;
  const newPassword = mode === "signup" || mode === "set-password";
  const email = byId("auth-email");
  const password = byId("auth-password");
  const confirm = byId("auth-confirm");
  const labels = {
    "sign-in": ["Sign in to V3.1", "Sign in to save and reopen your conversations.", "Sign in"],
    signup: ["Create an MKH account", "Use your preview team email. Choose a password with at least 12 characters.", "Create account"],
    recover: ["Set or reset your MKH password", "Open the link from your email in the browser where you request it.", "Email password link"],
    "set-password": ["Choose your MKH password", "Use at least 12 characters for your MKH password.", "Save password"],
  };
  const [title, description, submit] = labels[mode];
  byId("auth-title").textContent = title;
  byId("auth-description").textContent = description;
  byId("auth-submit").textContent = submit;
  byId("auth-email-wrap").classList.toggle("hidden", mode === "set-password");
  email.required = mode !== "set-password";
  byId("auth-password-wrap").classList.toggle("hidden", mode === "recover");
  password.required = mode !== "recover";
  password.minLength = newPassword ? 12 : 1;
  password.autocomplete = newPassword ? "new-password" : "current-password";
  byId("auth-confirm-wrap").classList.toggle("hidden", !newPassword);
  confirm.required = newPassword;
  password.value = "";
  confirm.value = "";
  byId("auth-login").classList.toggle("hidden", mode === "sign-in");
  byId("auth-signup").classList.toggle("hidden", mode !== "sign-in");
  byId("auth-recover").classList.toggle("hidden", mode !== "sign-in");
  authStatus(message);
  if (!dialog.open) dialog.showModal();
  (email.required ? email : password).focus();
}

async function submitAuth(event) {
  event.preventDefault();
  const button = byId("auth-submit");
  if (button.disabled) return;
  const mode = authMode;
  const password = byId("auth-password").value;
  if ((mode === "signup" || mode === "set-password") && password !== byId("auth-confirm").value) {
    authStatus("The passwords do not match.");
    return;
  }
  const payload = {};
  if (mode !== "set-password") payload.email = byId("auth-email").value.trim();
  if (mode !== "recover") payload.password = password;
  const controls = [button, byId("auth-login"), byId("auth-signup"), byId("auth-recover")];
  controls.forEach((control) => { control.disabled = true; });
  authStatus(mode === "recover" ? "Requesting a password email…" : "Please wait…");
  try {
    const result = await json("/api/auth/" + mode, payload);
    if (result.authenticated) {
      const draft = promptBox.value;
      await refreshSession();
      if (!session.authenticated) throw new Error("V3.1 could not open your session. Please sign in again.");
      reset();
      promptBox.value = draft;
      dialog.close();
      updateComposer();
    } else {
      const message = mode === "signup"
        ? "Open the verification link in your email to finish creating the account."
        : "If an eligible account matches this address, you’ll receive a password setup link.";
      openSignIn(mode, message);
    }
  } catch (failure) {
    authStatus(failure.message);
  } finally {
    controls.forEach((control) => { control.disabled = false; });
  }
}

function handleEmailLink() {
  const params = new URLSearchParams(location.search);
  const stage = params.get("auth");
  if (stage) {
    params.delete("auth");
    history.replaceState(null, "", location.pathname + (params.size ? "?" + params : ""));
  }
  if (session.password_setup_pending) {
    openSignIn("set-password");
  } else if (stage === "ready" && session.authenticated) {
    updateComposer("Account verified. Your V3.1 chats will be saved.");
  } else if (stage === "expired") {
    openSignIn("recover", "Request a fresh email link and open it in this browser.");
  }
}

async function* jobUpdates(run) {
  const deadline = Date.now() + 205000;
  const path = "/api/jobs/" + encodeURIComponent(run.id);
  let revision = -1;
  let failures = 0;
  let stream = typeof TextDecoderStream !== "undefined";
  while (Date.now() < deadline && !run.controller.signal.aborted) {
    const connection = new AbortController();
    const signal = AbortSignal.any([run.controller.signal, connection.signal]);
    let timer;
    const arm = (ms) => {
      clearTimeout(timer);
      timer = setTimeout(() => connection.abort(), Math.min(ms, Math.max(1, deadline - Date.now())));
    };
    try {
      if (stream) {
        // Some workplace proxies release an entire stream only when the response ends.
        arm(1800);
        const response = await request(path + "?watch=events", {signal});
        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        while (true) {
          const {value, done} = await reader.read();
          if (done) break;
          buffer += value;
          let end;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            if (!frame.startsWith("data: ")) continue;
            const data = JSON.parse(frame.slice(6));
            arm(5200);
            revision = data.revision;
            yield data;
            if (["answer", "error"].includes(data.event.type)) return;
          }
        }
      } else {
        arm(14000);
        const response = await request(path + "?after=" + revision, {signal});
        const data = await response.json();
        failures = 0;
        revision = data.revision;
        yield data;
        if (["answer", "error"].includes(data.event.type)) return;
        await new Promise((resolve) => setTimeout(resolve, 350));
      }
    } catch (failure) {
      if (run.controller.signal.aborted || [401, 403, 410].includes(failure.status)) throw failure;
      if (!stream) {
        if (++failures >= 4) break;
        updateComposer("Reconnecting to the research run…");
        await new Promise((resolve) => setTimeout(resolve, 500 * failures));
      }
    } finally {
      clearTimeout(timer);
      connection.abort();
    }
    stream = false;
  }
  throw new Error("Connection lost. You can resend your question or start a new chat.");
}

function showLive(run, event) {
  const scroller = byId("conversation-scroll");
  const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 110;
  if (!run.live) {
    run.started = Date.now();
    run.live = el("div", "message assistant live-answer");
    const card = el("div", "live-research");
    const head = el("div", "live-heading");
    run.label = el("span", "live-label");
    run.label.setAttribute("role", "status");
    run.elapsed = el("time", "live-elapsed");
    run.elapsed.setAttribute("aria-hidden", "true");
    run.clock = setInterval(() => {
      run.elapsed.textContent = Math.floor((Date.now() - run.started) / 1000) + "s";
    }, 1000);
    head.append(run.label, run.elapsed);
    run.trail = el("ul", "live-steps");
    card.append(head, run.trail);
    run.draft = el("div", "assistant-turn live-draft");
    run.draft.setAttribute("aria-live", "off");
    run.live.append(card, run.draft);
    messages.append(run.live);
  }
  const steps = event.research_steps || [];
  if (steps.length !== run.steps) {
    run.steps = steps.length;
    run.trail.replaceChildren(...steps.slice(-3).map((step) => {
      const line = el("li", "", [step.action, step.detail].filter(Boolean).join(" · "));
      if (step.status !== "completed") line.classList.add("incomplete");
      return line;
    }));
  }
  if (run.label.textContent !== event.text) run.label.textContent = event.text;
  // Citations become interactive after the server has verified and saved the turn.
  const draft = (event.draft || "").replace(/\[\[E-[0-9a-f]{0,16}(?:\]\]|\]?$)/g, "").replace(/\[{1,2}(?:E-?)?$/, "");
  if (draft !== run.draft.textContent) run.draft.textContent = draft;
  const status = draft ? "Draft · Final checks follow" : event.text + "…";
  if (statusLine.textContent !== status) updateComposer(status);
  if (nearBottom) scrollToLatest();
}

function stopResearch(restore = true) {
  const run = active;
  if (!run) return;
  active = null;
  run.controller.abort();
  sessionStorage.removeItem(pendingJobKey);
  clearInterval(run.clock);
  run.live?.remove();
  run.pending?.remove();
  if (restore && !promptBox.value) promptBox.value = run.prompt;
  byId("welcome").classList.toggle("hidden", messages.childElementCount > 0);
  updateComposer(restore ? "Assignment stopped." : "");
  // Wait for admission when Stop was clicked before the server returned its job ID.
  const prior = stopping;
  stopping = (async () => {
    await prior;
    const id = run.id || (await run.admission)?.job_id;
    if (id) await request("/api/jobs/" + encodeURIComponent(id), {method: "DELETE"});
  })().catch(() => {});
}

async function runAssignment(prompt, resumeId) {
  const run = {controller: new AbortController(), id: resumeId, prompt};
  active = run;
  viewRevision++;
  try {
    if (!resumeId) {
      promptBox.value = "";
      run.pending = appendUser(prompt);
      showLive(run, {text: "Sending your question"});
      await stopping;
      if (active !== run) return;
      run.admission = json("/api/chat", {prompt, instructions: workingInstructions, delivery: "job",
        conversation_id: conversationId, signed_in: session.authenticated, mode: byId("analysis-mode").value});
      const job = await run.admission;
      run.id = job.job_id;
      if (active !== run) return;
      sessionStorage.setItem(pendingJobKey, run.id);
    }
    for await (const status of jobUpdates(run)) {
      if (active !== run) return;
      const event = status.event;
      if (!run.pending) {
        run.prompt = status.prompt;
        workingInstructions = status.instructions;
        run.pending = appendUser(run.prompt);
      }
      if (event.type === "error") throw new Error(event.text);
      if (event.type === "answer") {
        conversationId = event.conversation_id;
        sessionStorage.setItem(conversationKey, conversationId);
        currentRequirements = event.requirements || {};
        clearInterval(run.clock);
        run.live?.remove();
        appendAnswer({...event, prompt: run.prompt});
        sessionStorage.removeItem(pendingJobKey);
        active = null;
        updateComposer();
        recent().catch(() => {});
        return;
      }
      showLive(run, event);
    }
  } catch (failure) {
    if (active !== run) return;
    stopResearch(false);
    if (!promptBox.value) promptBox.value = run.prompt;
    if (failure.status === 401) {
      conversationId = null;
      sessionStorage.removeItem(conversationKey);
      await refreshSession().catch(() => {});
    }
    if (failure.status === 410 && !resumeId) {
      conversationId = null;
      sessionStorage.removeItem(conversationKey);
    }
    if (!active) updateComposer(failure.message);
  }
}

async function send() {
  const prompt = promptBox.value.trim();
  if (active || !prompt) return;
  if (!session) {
    try { await refreshSession(); } catch (failure) { updateComposer(failure.message); return; }
    if (active) return;
  }
  if (!session?.chat_enabled) {
    updateComposer(session ? "Model-backed chat is temporarily unavailable. Your draft is kept here."
                           : "The preview is connecting. Try Send again in a moment.");
    return;
  }
  await runAssignment(prompt, null);
}

function setSidebar(open) {
  byId("workspace").classList.toggle("sidebar-hidden", !open);
  byId("sidebar-scrim").classList.toggle("hidden", !open);
}

async function editNotes(personal) {
  openDrawer(personal ? "Personal memory" : "Working instructions");
  const viewSession = session;
  try {
    const saved = personal ? await json("/api/memory") : {notes: workingInstructions};
    if (viewSession !== session || drawer.classList.contains("hidden")) return;
    const form = el("form", "notes-form");
    const description = personal
      ? "Choose what the Companion remembers across your chats. Only you can edit these notes."
      : "Set the audience, scope or format for this chat. These instructions travel with your next message.";
    const label = el("label", "", personal ? "My preferences and recurring assignments" : "Instructions for this chat");
    const textarea = el("textarea");
    textarea.id = "notes-editor"; textarea.maxLength = 2000; textarea.rows = 7;
    textarea.value = saved.notes; label.htmlFor = textarea.id;
    form.append(el("p", "", description), label, textarea);
    const toggle = el("input");
    if (personal) {
      toggle.type = "checkbox"; toggle.checked = saved.enabled;
      const check = el("label", "memory-toggle");
      check.append(toggle, document.createTextNode(" Use personal memory in my chats"));
      form.append(check);
    }
    const save = el("button", "primary-button", personal ? "Save memory" : "Apply to this chat");
    const notice = el("p", "evidence-meta");
    form.append(save, notice);
    if (personal && saved.notes) form.append(action("Delete memory", async () => {
      try {
        await json("/api/memory", {notes: "", enabled: false});
        closeDrawer();
      } catch (failure) { notice.textContent = failure.message; }
    }));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      try {
        if (personal) await json("/api/memory", {notes: textarea.value, enabled: toggle.checked});
        else workingInstructions = textarea.value.trim();
        closeDrawer();
      } catch (failure) { notice.textContent = failure.message; }
      finally { save.disabled = false; }
    });
    if (!personal && Object.keys(currentRequirements).length) {
      const heading = el("h3", "", "Requirements from this conversation");
      const list = el("ul");
      for (const [dimension, quote] of Object.entries(currentRequirements)) {
        list.append(el("li", "", dimension.replaceAll("_", " ") + " · " + quote));
      }
      drawerBody.append(heading, list);
    }
    drawerBody.append(form);
    textarea.focus();
  } catch (failure) { drawerBody.replaceChildren(el("p", "", failure.message)); }
}

byId("working-notes").addEventListener("click", () => editNotes(false));
byId("personal-memory").addEventListener("click", () => editNotes(true));
if (window.innerWidth <= 800) setSidebar(false);
byId("earlier-turns").addEventListener("click", loadEarlier);
byId("sources-toggle").addEventListener("click", () => showCatalogue());
byId("drawer-close").addEventListener("click", closeDrawer);
byId("drawer-scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !drawer.classList.contains("hidden")) closeDrawer();
});
byId("sidebar-open").addEventListener("click", () => setSidebar(true));
byId("sidebar-collapse").addEventListener("click", () => setSidebar(false));
byId("sidebar-scrim").addEventListener("click", () => setSidebar(false));
byId("new-chat").addEventListener("click", () => { stopResearch(false); reset(); promptBox.focus(); });
byId("profile-button").addEventListener("click", async () => {
  try {
    if (session?.authenticated) {
      if (active) return;
      await json("/api/auth/signout", {});
      reset();
      await refreshSession();
    } else {
      openSignIn();
    }
  } catch (failure) {
    updateComposer(failure.message);
  }
});
byId("auth-form").addEventListener("submit", submitAuth);
byId("auth-login").addEventListener("click", () => openSignIn());
byId("auth-signup").addEventListener("click", () => openSignIn("signup"));
byId("auth-recover").addEventListener("click", () => openSignIn("recover"));
dialog.addEventListener("close", () => {
  byId("auth-password").value = "";
  byId("auth-confirm").value = "";
  if (!active) promptBox.focus();
});
byId("composer-sign-in").addEventListener("click", () => openSignIn());
byId("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  send();
});
byId("cancel-button").addEventListener("click", () => stopResearch());
promptBox.addEventListener("input", () => { if (!active) updateComposer(); });
promptBox.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    byId("composer").requestSubmit();
  }
});
document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    promptBox.value = button.textContent;
    updateComposer();
    promptBox.focus();
  });
});
refreshSession().then(async () => {
  handleEmailLink();
  const id = sessionStorage.getItem(pendingJobKey);
  const chat = sessionStorage.getItem(conversationKey);
  const opening = viewRevision;
  if (chat && !dialog.open && !active) {
    try {
      const saved = await json("/api/conversations/" + encodeURIComponent(chat));
      if (opening !== viewRevision || active) return;
      conversationId = chat;
      currentRequirements = saved.turns.at(-1)?.requirements || {};
      workingInstructions = saved.turns.at(-1)?.instructions || "";
      showSavedTurns(saved, messages);
      if (id && saved.turns.some((turn) => turn.run_id === id)) {
        sessionStorage.removeItem(pendingJobKey);
        return;
      }
      if (saved.title) byId("topbar-title").textContent = saved.title;
    } catch (failure) {
      if (opening !== viewRevision || active) return;
      if ([401, 404, 410].includes(failure.status)) sessionStorage.removeItem(conversationKey);
    }
  }
  if (id && !dialog.open && !active && opening === viewRevision) runAssignment("", id);
}).catch((failure) => updateComposer(failure.message));
