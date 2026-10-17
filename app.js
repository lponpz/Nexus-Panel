const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const toast = message => { const el = $("#toast"); el.textContent = message; el.classList.add("show"); clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => el.classList.remove("show"), 3000); };
const pages = {
  "Overview":["Your hosting, <span>in one place.</span>","A unified command center for every connected game hosting panel."],
  "Game Servers":["Every server, <span>one view.</span>","Review server status and supported actions across connected panels."],
  "Panel Connectors":["Connect your <span>hosting world.</span>","Manage adapters, health, versions and supported capabilities."],
  "Nodes & Capacity":["Capacity without <span>guesswork.</span>","Plan placement using reported resources, limits and node health."],
  "Backups & Recovery":["Recovery you can <span>trust.</span>","Review backup health, restore readiness and recovery policies."],
  "Store & Billing":["Your hosting <span>business center.</span>","Plans, orders, currencies and billing integrations in one workspace."],
  "Customers & Resellers":["Every tenant, <span>properly separated.</span>","Manage customer access, reseller quotas and tenant boundaries."],
  "Automation & AI":["Less repetition. <span>More control.</span>","Review workflows, diagnostic suggestions and approval-gated actions."],
  "Extensions":["Make Nexus <span>your own.</span>","Explore connectors and permission-scoped extensions."],
  "Security & Audit":["Security with <span>visibility.</span>","Review access events, sensitive actions and integration health."],
  "Settings":["Tune your <span>workspace.</span>","Branding, themes, localization, access policy and preferences."]
};
function showPage(page) {
  $$(".nav-link").forEach(button => button.classList.toggle("active", button.dataset.page === page));
  $("#breadcrumb").textContent = page;
  const copy = pages[page] || pages.Overview;
  $("#pageTitle").innerHTML = copy[0];
  $("#pageSubtitle").textContent = copy[1];
  closeMenu();
  if (page !== "Overview") toast(page + ": navigation preview only. This module is not connected to a backend yet.");
}
$$("[data-page]").forEach(el => el.addEventListener("click", () => showPage(el.dataset.page)));
function openDialog() { const dialog = $("#connectDialog"); if (dialog.showModal) dialog.showModal(); else toast("Please use a modern browser to preview the connector form."); }
$("#connect").addEventListener("click", openDialog);
$("#addConnector").addEventListener("click", openDialog);
$("#closeDialog").addEventListener("click", () => $("#connectDialog").close());
$("#connectForm").addEventListener("submit", event => {
  event.preventDefault();
  const type = $("#panelType").value, url = $("#panelUrl").value.trim();
  if (!type || !url) return toast("Choose a panel type and enter its base URL.");
  $("#connectDialog").close();
  toast("Setup preview captured for " + type + ". No network request was made.");
  $("#connectForm").reset();
});
$("#refresh").addEventListener("click", () => toast("Prototype refreshed. Dashboard values are sample data."));
$("#notifications").addEventListener("click", () => toast("Notifications center is planned; no live events are connected."));
$("#activityOptions").addEventListener("click", () => toast("Activity filters will be available with the audit module."));
$("#profileMenu").addEventListener("click", () => toast("Profile and session settings are planned for a later phase."));
$("#search").addEventListener("input", event => {
  const query = event.target.value.toLowerCase().trim();
  $$(".connector, #serverRows tr").forEach(row => {
    row.hidden = !!query && !(row.innerText + " " + (row.dataset.search || "")).toLowerCase().includes(query);
  });
});
$$(".more").forEach(button => button.addEventListener("click", () => toast("Server and connector actions require a verified live adapter; this prototype makes no remote changes.")));
const sidebar = $("#sidebar"), scrim = $("#scrim");
function openMenu(){ sidebar.classList.add("open"); scrim.classList.add("show"); }
function closeMenu(){ sidebar.classList.remove("open"); scrim.classList.remove("show"); }
$("#openMenu").addEventListener("click", openMenu);
$("#closeMenu").addEventListener("click", closeMenu);
scrim.addEventListener("click", closeMenu);
document.addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#search").focus(); }
  if (event.key === "Escape") closeMenu();
});