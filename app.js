const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const toast = message => { const el = $("#toast"); el.textContent = message; el.classList.add("show"); clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => el.classList.remove("show"), 3500); };
const pages = {
  "Overview":["Your hosting, <span>in one place.</span>","A unified command center for your saved game hosting records."],
  "Game Servers":["Every server, <span>one view.</span>","Manage local server records. Live start/stop controls require a host adapter."],
  "Panel Connectors":["Connect your <span>hosting world.</span>","Save panel endpoints. Live authentication and capability discovery are not implemented yet."],
  "Nodes & Capacity":["Capacity without <span>guesswork.</span>","Live resource telemetry requires a connected node adapter."],
  "Backups & Recovery":["Recovery you can <span>trust.</span>","Backup storage and restore operations are not configured in this MVP."],
  "Store & Billing":["Your hosting <span>business center.</span>","Billing integrations are not configured in this MVP."],
  "Customers & Resellers":["Every tenant, <span>properly separated.</span>","Multi-user accounts and tenant access are not configured yet."],
  "Automation & AI":["Less repetition. <span>More control.</span>","Automation requires explicit workflows and verified adapters."],
  "Extensions":["Make Nexus <span>your own.</span>","Extension SDK and marketplace are planned for a later phase."],
  "Security & Audit":["Security with <span>visibility.</span>","This MVP has a local activity log but does not yet provide user authentication."],
  "Settings":["Tune your <span>workspace.</span>","Branding, access policy and integration settings will be expanded."]
};
function showPage(page) {
  $$(".nav-link").forEach(button => button.classList.toggle("active", button.dataset.page === page));
  $("#breadcrumb").textContent = page;
  const copy = pages[page] || pages.Overview;
  $("#pageTitle").innerHTML = copy[0]; $("#pageSubtitle").textContent = copy[1]; closeMenu();
  if (page !== "Overview") toast(copy[1]);
}
$$("[data-page]").forEach(el => el.addEventListener("click", () => showPage(el.dataset.page)));
function openDialog() { const dialog = $("#connectDialog"); if (dialog.showModal) dialog.showModal(); else toast("Please use a modern browser."); }
$("#connect").addEventListener("click", openDialog);
$("#addServer").addEventListener("click", () => $("#serverDialog").showModal());
$("#addConnector").addEventListener("click", openDialog);
$("#closeDialog").addEventListener("click", () => $("#connectDialog").close());
$("#closeServerDialog").addEventListener("click", () => $("#serverDialog").close());
async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type":"application/json"}, ...options});
  const data = await response.json().catch(() => ({ok:false,error:"Server returned an invalid response"}));
  if (!response.ok || data.ok === false) throw new Error(data.error || ("Request failed: " + response.status));
  return data;
}
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const gameClass = game => game === "Minecraft" ? "mc" : game === "FiveM" ? "fivem" : game === "Terraria" ? "terraria" : "";
const gameLetter = game => game === "Minecraft" ? "M" : game === "FiveM" ? "F" : game === "Terraria" ? "T" : "•";
function renderServers(items) {
  const tbody = $("#serverRows");
  if (!items.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No server records yet. Use “Game Servers” to create one.</td></tr>'; return; }
  tbody.innerHTML = items.map(item => '<tr data-search="' + esc([item.name,item.game,item.panel].join(" ").toLowerCase()) + '">' +
    '<td><div class="server-name"><span class="game ' + gameClass(item.game) + '">' + gameLetter(item.game) + '</span><div><strong>' + esc(item.name) + '</strong><small>' + esc(item.id.slice(0,8)) + '</small></div></div></td>' +
    '<td>' + esc(item.game) + '</td><td><span class="tag">' + esc(item.panel) + '</span></td>' +
    '<td><span class="server-status ' + (item.status === "Stopped" ? "stopped" : "running") + '"><i></i>' + esc(item.status) + '</span></td>' +
    '<td><span>Not connected</span></td><td><button class="record-delete" data-delete-server="' + esc(item.id) + '">Delete</button></td></tr>').join("");
}
function renderConnectors(items) {
  const root = $("#connectors");
  if (!items.length) { root.innerHTML = '<p class="empty-state">No connectors saved yet. Use “Connect panel” to save an endpoint.</p>'; return; }
  root.innerHTML = items.map(item => {
    const cls = item.panel_type === "Pterodactyl" ? "ptero" : item.panel_type === "Pelican Panel" ? "pelican" : "amp";
    const letter = item.panel_type === "AMP by CubeCoders" ? "A" : item.panel_type === "Custom adapter (SDK)" ? "C" : "P";
    return '<div class="connector" data-search="' + esc((item.panel_type+" "+item.base_url).toLowerCase()) + '">' +
      '<div class="connector-logo ' + cls + '">' + letter + '</div><div class="connector-info"><strong>' + esc(item.panel_type) + '</strong><small>' + esc(item.base_url) + ' · saved locally</small></div>' +
      '<span class="connection-state limited"><i></i>' + esc(item.status) + '</span><button class="record-delete" data-delete-connector="' + esc(item.id) + '">Delete</button></div>';
  }).join("");
}
function renderActivities(items) {
  const root = $("#activityList");
  if (!items.length) { root.innerHTML = '<p class="empty-state">Activity will appear here as you use the app.</p>'; return; }
  root.innerHTML = items.map(item => '<div class="activity"><span class="activity-icon blue-bg">•</span><div><strong>' + esc(item.message) + '</strong><p>' + esc(item.detail) + '</p><small>' + esc(new Date(item.created_at).toLocaleString()) + '</small></div></div>').join("");
}
async function refreshDashboard() {
  try {
    const results = await Promise.all([api("/api/health"),api("/api/overview"),api("/api/servers"),api("/api/connectors")]);
    const overview = results[1], servers = results[2], connectors = results[3];
    $("#connectorCount").innerHTML = overview.connectors + ' <small>saved</small>';
    $("#navConnectorCount").textContent = overview.connectors;
    $("#serverCount").innerHTML = overview.servers + ' <small>saved</small>';
    $("#navServerCount").textContent = overview.servers;
    $("#serverCountLabel").textContent = overview.servers + " records";
    $("#serverProgress").style.width = overview.servers ? "100%" : "0%";
    renderServers(servers.items); renderConnectors(connectors.items); renderActivities(overview.activities);
    const footer = $(".footer span:last-child");
    if (footer) footer.innerHTML = '<i></i> Backend online · SQLite local MVP';
    return true;
  } catch (error) { toast("Backend connection failed: " + error.message + ". Start with bash ./nexus."); return false; }
}
$("#connectForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/connectors",{method:"POST",body:JSON.stringify({panel_type:$("#panelType").value,base_url:$("#panelUrl").value.trim()})});
    $("#connectDialog").close(); $("#connectForm").reset();
    toast("Connector endpoint saved. It has NOT been tested or authenticated."); await refreshDashboard();
  } catch (error) { toast(error.message); }
});
$("#serverForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/servers",{method:"POST",body:JSON.stringify({name:$("#serverName").value.trim(),game:$("#serverGame").value,panel:$("#serverPanel").value,status:"Configured"})});
    $("#serverDialog").close(); $("#serverForm").reset(); toast("Server record created in the local database."); await refreshDashboard();
  } catch (error) { toast(error.message); }
});
document.addEventListener("click", async event => {
  const serverId = event.target.closest("[data-delete-server]")?.dataset.deleteServer;
  const connectorId = event.target.closest("[data-delete-connector]")?.dataset.deleteConnector;
  if (serverId) {
    if (!confirm("Delete this saved server record? This does not delete a real game server.")) return;
    try { await api("/api/servers/"+encodeURIComponent(serverId),{method:"DELETE"}); toast("Server record deleted."); await refreshDashboard(); } catch (error) { toast(error.message); }
  }
  if (connectorId) {
    if (!confirm("Remove this saved connector record? No remote panel will be changed.")) return;
    try { await api("/api/connectors/"+encodeURIComponent(connectorId),{method:"DELETE"}); toast("Connector record removed."); await refreshDashboard(); } catch (error) { toast(error.message); }
  }
});
$("#refresh").addEventListener("click", async () => { if (await refreshDashboard()) toast("Dashboard refreshed from the local backend."); });
$("#notifications").addEventListener("click", () => toast("Live notifications are not implemented yet."));
$("#activityOptions").addEventListener("click", () => toast("Showing the latest local activity records."));
$("#profileMenu").addEventListener("click", () => toast("User login and profile settings are not implemented in this MVP."));
$("#search").addEventListener("input", event => {
  const query = event.target.value.toLowerCase().trim();
  $$(".connector, #serverRows tr").forEach(row => { row.hidden = !!query && !(row.innerText + " " + (row.dataset.search || "")).toLowerCase().includes(query); });
});
const sidebar = $("#sidebar"), scrim = $("#scrim");
function openMenu(){ sidebar.classList.add("open"); scrim.classList.add("show"); }
function closeMenu(){ sidebar.classList.remove("open"); scrim.classList.remove("show"); }
$("#openMenu").addEventListener("click", openMenu); $("#closeMenu").addEventListener("click", closeMenu); scrim.addEventListener("click", closeMenu);
document.addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#search").focus(); }
  if (event.key === "Escape") closeMenu();
});
refreshDashboard();
