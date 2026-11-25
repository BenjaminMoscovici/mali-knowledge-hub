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
let active = null;
let codeSent = false;
let submitAfterSignIn = false;
let opener = null;

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    const error = new Error(failure.error || "The V3 preview could not complete this request.");
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
  byId("send-button").disabled = Boolean(active) || !promptBox.value.trim();
  byId("send-button").title = needsSignIn ? "Sign in to send" : "Send question";
  byId("cancel-button").classList.toggle("hidden", !active);
  byId("new-chat").disabled = Boolean(active);
  promptBox.readOnly = Boolean(active);
  statusLine.textContent = status || (
    !session ? "Checking the V3 preview session…" :
      !session.model_configured ? "V3 preview · Source browsing is available. Model access is being configured." :
        !session.authenticated ? "Sign in with your email code to send a message." :
        "V3 preview · Saved to your V3 account."
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
  if (data.rows) card.append(dataTable(data.rows));
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

async function showCatalogue(initial = "") {
  openDrawer("What the Hub knows");
  const form = el("form", "catalogue-search");
  const input = el("input");
  input.type = "search";
  input.placeholder = "Search approved sources";
  input.setAttribute("aria-label", "Search approved sources");
  input.value = initial;
  const submit = el("button", "sources-button", "Search");
  form.append(input, submit);
  const results = el("div");
  drawerBody.append(form, results);
  async function load() {
    results.replaceChildren(el("p", "evidence-meta", "Loading approved sources…"));
    try {
      const {sources} = await json("/api/sources?q=" + encodeURIComponent(input.value));
      results.replaceChildren();
      if (!sources.length) results.append(el("p", "evidence-meta", "No matching published sources."));
      for (const item of sources) {
        const card = el("article", "evidence-item");
        const detail = el("button", "source-title", item.title);
        detail.type = "button";
        detail.addEventListener("click", () => showSource(item.id, input.value));
        card.append(detail, el("p", "evidence-meta", [item.publisher, item.period].filter(Boolean).join(" · ")),
          el("p", "source-description", item.description));
        results.append(card);
      }
    } catch (failure) {
      results.replaceChildren(el("p", "evidence-meta", failure.message));
    }
  }
  form.addEventListener("submit", (event) => { event.preventDefault(); load(); });
  await load();
}

async function showSource(id, previousQuery) {
  openDrawer("Source details");
  try {
    const info = await json("/api/sources/" + encodeURIComponent(id));
    if (drawer.classList.contains("hidden")) return;
    drawer.querySelector("h2").textContent = info.title;
    const back = el("button", "sources-button", "Back to sources");
    back.addEventListener("click", () => showCatalogue(previousQuery));
    drawerBody.append(back, el("p", "source-description", info.description),
      el("p", "evidence-meta", [info.publisher, info.release, info.geography, info.period, info.license]
        .filter(Boolean).join(" · ")));
    const list = el("ul", "source-limits");
    for (const line of info.limitations || []) list.append(el("li", "", line));
    drawerBody.append(list);
    const original = link(info.url, "Open original publication ↗");
    if (original) drawerBody.append(original);
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

function appendUser(text) {
  byId("welcome").classList.add("hidden");
  const node = el("div", "message user");
  node.append(el("div", "user-bubble", text));
  messages.append(node);
  scrollToLatest();
  return node;
}

function appendAnswer(turn) {
  const evidence = turn.evidence || [];
  const message = el("div", "message assistant");
  const body = el("div", "assistant-turn");
  renderAnswer(body, turn.answer || turn.text, evidence);
  message.append(body);
  const footer = el("div", "message-footer");
  if (evidence.length) {
    const view = el("button", "sources-button", `View sources (${evidence.length})`);
    view.addEventListener("click", () => showEvidence(evidence));
    footer.append(view);
  }
  if (turn.partial || turn.tool_failures?.length) {
    footer.append(el("span", "", turn.partial ? "Research incomplete" : "Some research tools could not complete"));
  }
  message.append(footer);
  messages.append(message);
  scrollToLatest();
}

function reset() {
  conversationId = null;
  messages.replaceChildren();
  byId("welcome").classList.remove("hidden");
  byId("topbar-title").textContent = "Mali Knowledge Hub";
  promptBox.value = "";
  updateComposer();
}

async function recent() {
  const list = byId("thread-list");
  list.replaceChildren();
  if (!session?.authenticated) return;
  const data = await json("/api/conversations");
  for (const entry of data.conversations) {
    const row = el("div", "thread-row");
    const button = el("button", "thread-title", entry.title);
    button.addEventListener("click", async () => {
      if (active) return;
      try {
        const value = await json("/api/conversations/" + entry.id);
        reset();
        conversationId = entry.id;
        byId("topbar-title").textContent = entry.title;
        for (const turn of value.turns) {
          appendUser(turn.prompt);
          if (turn.answer) appendAnswer(turn);
          if (turn.withdrawn) messages.append(el("p", "evidence-meta", "Earlier evidence is outside the current approved scope."));
        }
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
  byId("profile-title").textContent = session.authenticated ? "Sign out" : "Sign in";
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

function showCode(visible) {
  codeSent = visible;
  byId("code-wrap").classList.toggle("hidden", !visible);
  byId("auth-resend").classList.toggle("hidden", !visible);
  byId("auth-change-email").classList.toggle("hidden", !visible);
  byId("auth-email").readOnly = visible;
  byId("auth-submit").textContent = visible ? "Sign in" : "Send code";
  byId("auth-code").required = visible;
  byId("auth-code").value = "";
  if (visible) byId("auth-code").focus();
}

function openSignIn(resume = false, message = "") {
  if (!session?.auth_enabled) {
    updateComposer("V3 sign-in is temporarily unavailable.");
    return;
  }
  if (dialog.open) return;
  submitAfterSignIn = resume;
  showCode(false);
  authStatus(message);
  dialog.showModal();
  byId("auth-email").focus();
}

async function submitAuth(event) {
  event.preventDefault();
  const email = byId("auth-email").value.trim();
  const requestCode = !codeSent || event.currentTarget === byId("auth-resend");
  const button = byId("auth-submit");
  if (button.disabled) return;
  button.disabled = true;
  byId("auth-resend").disabled = true;
  byId("auth-change-email").disabled = true;
  try {
    if (requestCode) {
      await json("/api/auth/request-code", {email});
      authStatus("Enter the one-time code from the latest MKH V3 email.");
      showCode(true);
    } else {
      await json("/api/auth/verify-code", {email, code: byId("auth-code").value.trim()});
      await refreshSession();
      if (!session.authenticated) throw new Error("V3 could not open your session. Request a new code.");
      const resume = submitAfterSignIn;
      submitAfterSignIn = false;
      dialog.close();
      if (resume) send();
    }
  } catch (failure) {
    authStatus(failure.message);
  } finally {
    button.disabled = false;
    byId("auth-resend").disabled = false;
    byId("auth-change-email").disabled = false;
  }
}

async function send() {
  const prompt = promptBox.value.trim();
  if (active || !prompt) return;
  if (!session) {
    updateComposer("The preview is connecting. Try Send again in a moment.");
    return;
  }
  if (!session.authenticated) {
    openSignIn(true, "Sign in to send your draft. Your message is kept here.");
    return;
  }
  if (!session.chat_enabled) {
    updateComposer("Model-backed chat is temporarily unavailable. Your draft is kept here.");
    return;
  }
  active = new AbortController();
  promptBox.value = "";
  const pendingMessage = appendUser(prompt);
  updateComposer("Starting the assignment…");
  let completed = false;
  try {
    const response = await request("/api/chat", {
      method: "POST", signal: active.signal,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({prompt, conversation_id: conversationId, mode: byId("analysis-mode").value}),
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    while (true) {
      const {value, done} = await reader.read();
      pending += decoder.decode(value, {stream: !done});
      const lines = pending.split("\n");
      pending = lines.pop();
      for (const line of lines) {
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.type === "activity") updateComposer(event.text + "…");
        if (event.type === "error") throw new Error(event.text);
        if (event.type === "answer") {
          conversationId = event.conversation_id;
          appendAnswer(event);
          completed = true;
        }
      }
      if (done) break;
    }
    if (!completed) throw new Error("The connection ended before the answer completed.");
    await recent().catch(() => {});
    active = null;
    updateComposer();
  } catch (failure) {
    active = null;
    if (completed) {
      updateComposer();
      return;
    }
    pendingMessage.remove();
    byId("welcome").classList.toggle("hidden", messages.childElementCount > 0);
    if (failure.status === 401) {
      session = {...session, authenticated: false, chat_enabled: false};
      byId("profile-title").textContent = "Sign in";
      byId("thread-list").replaceChildren();
      reset();
      promptBox.value = prompt;
      updateComposer("Your session expired. Sign in again to send your draft.");
      openSignIn(false, "Your session expired. Sign in again to continue.");
      return;
    }
    promptBox.value = prompt;
    updateComposer(failure.name === "AbortError" ? "Assignment stopped." : failure.message);
  }
}

function setSidebar(open) {
  byId("workspace").classList.toggle("sidebar-hidden", !open);
  byId("sidebar-scrim").classList.toggle("hidden", !open);
}

if (window.innerWidth <= 800) setSidebar(false);
byId("sources-toggle").addEventListener("click", () => showCatalogue());
byId("drawer-close").addEventListener("click", closeDrawer);
byId("drawer-scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !drawer.classList.contains("hidden")) closeDrawer();
});
byId("sidebar-open").addEventListener("click", () => setSidebar(true));
byId("sidebar-collapse").addEventListener("click", () => setSidebar(false));
byId("sidebar-scrim").addEventListener("click", () => setSidebar(false));
byId("new-chat").addEventListener("click", () => { reset(); promptBox.focus(); });
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
byId("auth-resend").addEventListener("click", submitAuth);
byId("auth-change-email").addEventListener("click", () => {
  showCode(false);
  authStatus("");
  byId("auth-email").focus();
});
dialog.addEventListener("close", () => {
  submitAfterSignIn = false;
  byId("auth-code").value = "";
  if (!active) promptBox.focus();
});
byId("composer-sign-in").addEventListener("click", () => openSignIn());
byId("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  send();
});
byId("cancel-button").addEventListener("click", () => active?.abort());
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
refreshSession().catch((failure) => updateComposer(failure.message));
