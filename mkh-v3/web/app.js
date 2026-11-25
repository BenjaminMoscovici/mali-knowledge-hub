"use strict";

const byId = (id) => document.getElementById(id);
const promptBox = byId("prompt");
const statusLine = byId("preview-status");
const drawer = byId("evidence-drawer");

function openSources() {
  byId("drawer-body").textContent = "The approved V3 source catalogue is being connected.";
  drawer.classList.remove("hidden");
  byId("drawer-scrim").classList.remove("hidden");
  byId("drawer-close").focus();
}

function closeSources() {
  drawer.classList.add("hidden");
  byId("drawer-scrim").classList.add("hidden");
  byId("sources-toggle").focus();
}

byId("sources-toggle").addEventListener("click", openSources);
byId("drawer-close").addEventListener("click", closeSources);
byId("drawer-scrim").addEventListener("click", closeSources);
byId("sidebar-open").addEventListener("click", () => byId("workspace").classList.toggle("sidebar-open"));
byId("sidebar-collapse").addEventListener("click", () => byId("workspace").classList.toggle("sidebar-collapsed"));
byId("sidebar-scrim").addEventListener("click", () => byId("workspace").classList.remove("sidebar-open"));
byId("new-chat").addEventListener("click", () => {
  promptBox.value = "";
  promptBox.focus();
});
document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    promptBox.value = button.textContent;
    promptBox.focus();
  });
});

fetch("/api/health")
  .then((result) => {
    if (!result.ok) throw new Error("Preview unavailable");
    return result.json();
  })
  .then(() => { statusLine.textContent = "V3 preview · Research tools are being connected."; })
  .catch(() => { statusLine.textContent = "Preview status is temporarily unavailable."; });
