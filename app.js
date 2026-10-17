const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const toast = message => { const el = $("#toast"); el.textContent = message; el.classList.add("show"); clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => el.classList.remove("show"), 3500); };
const pages = {
  "Overview":["Your hosting, <span>in one place.</span>","A unified command center for your saved game hosting records."],
  "Game Servers":["Every server, <span>one view.</span>","Open a server to edit its record, game, panel assignment and local status."],
  "Panel Connectors":["Connect your <span>hosting world.</span>","Review saved endpoints. Live authentication and external panel control still require adapters."],
  "Nodes & Capacity":["Capacity without <span>guesswork.</span>","Node telemetry appears here once a real node agent is implemented."],
  "Backups & Recovery":["Recovery you can <span>trust.</span>","Backup policies and restore operations need a configured storage provider."],
  "Store & Billing":["Your hosting <span>business center.</span>","Plans, invoices and payments will appear here when billing is implemented."],
  "Customers & Resellers":["Every tenant, <span>properly separated.</span>","Customer accounts and role-based tenant access are not implemented yet."],
  "Automation & AI":["Less repetition. <span>More control.</span>","Create safe workflows here in a later phase; no background jobs run yet."],
  "Extensions":["Make Nexus <span>your own.</span>","Manage add-ons here when the extension system is available."],
  "Security & Audit":["Security with <span>visibility.</span>","Review locally recorded changes. Owner login and permissions still need implementation."],
  "Settings":["Tune your <span>workspace.</span>","Workspace and integration settings."]
};
let currentPage = "Overview";
let cachedServers = [];
let cachedConnectors = [];
function closeMenu(){ $("#sidebar").classList.remove("open"); $("#scrim").classList.remove("show"); }
function openMenu(){ $("#sidebar").classList.add("open"); $("#scrim").classList.add("show"); }
async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type":"application/json"}, ...options});
  const data = await response.json().catch(() => ({ok:false,error:"Server returned an invalid response"}));
  if (!response.ok || data.ok === false) throw new Error(data.error || ("Request failed: " + response.status));
  return data;
}
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const gameClass = game => game === "Minecraft" ? "mc" : game === "FiveM" ? "fivem" : game === "Terraria" ? "terraria" : "";
const gameLetter = game => game === "Minecraft" ? "M" : game === "FiveM" ? "F" : game === "Terraria" ? "T" : "•";
const statusClass = status => status === "Stopped" ? "stopped" : status === "Maintenance" ? "maintenance" : "configured";
function renderServers(items) {
  cachedServers = items;
  const tbody = $("#serverRows");
  if (tbody) tbody.innerHTML = !items.length ? '<tr><td colspan="6" class="empty-state">No server records yet. Use “Add server” to create one.</td></tr>' :
    items.map(item => '<tr data-search="' + esc([item.name,item.game,item.panel].join(" ").toLowerCase()) + '">' +
      '<td><div class="server-name"><span class="game ' + gameClass(item.game) + '">' + gameLetter(item.game) + '</span><div><strong>' + esc(item.name) + '</strong><small>' + esc(item.id.slice(0,8)) + '</small></div></div></td>' +
      '<td>' + esc(item.game) + '</td><td><span class="tag">' + esc(item.panel) + '</span></td>' +
      '<td><span class="server-status ' + statusClass(item.status) + '"><i></i>' + esc(item.status) + '</span></td>' +
      '<td><span>Not connected</span></td><td><button class="record-manage" data-manage-server="' + esc(item.id) + '">Manage</button></td></tr>').join("");
}
function renderConnectors(items) {
  cachedConnectors = items;
  const root = $("#connectors");
  if (root) root.innerHTML = !items.length ? '<p class="empty-state">No connectors saved yet. Use “Connect panel” to save an endpoint.</p>' :
    items.map(item => {
      const cls = item.panel_type === "Pterodactyl" ? "ptero" : item.panel_type === "Pelican Panel" ? "pelican" : "amp";
      const letter = item.panel_type === "AMP by CubeCoders" ? "A" : item.panel_type === "Custom adapter (SDK)" ? "C" : "P";
      return '<div class="connector" data-search="' + esc((item.panel_type+" "+item.base_url).toLowerCase()) + '">' +
        '<div class="connector-logo ' + cls + '">' + letter + '</div><div class="connector-info"><strong>' + esc(item.panel_type) + '</strong><small>' + esc(item.base_url) + ' · saved locally</small></div>' +
        '<span class="connection-state limited"><i></i>' + esc(item.status) + '</span><button class="record-delete" data-delete-connector="' + esc(item.id) + '">Delete</button></div>';
    }).join("");
}
function renderActivities(items) {
  const root = $("#activityList");
  if (!root) return;
  root.innerHTML = !items.length ? '<p class="empty-state">Activity will appear here as you use the app.</p>' :
    items.map(item => '<div class="activity"><span class="activity-icon blue-bg">•</span><div><strong>' + esc(item.message) + '</strong><p>' + esc(item.detail) + '</p><small>' + esc(new Date(item.created_at).toLocaleString()) + '</small></div></div>').join("");
}
function renderPageWorkspace(page) {
  const root = $("#pageWorkspace");
  if (page === "Overview") { root.hidden = true; return; }
  root.hidden = false;
  if (page === "Game Servers") {
    root.innerHTML = '<section class="card workspace-card"><div class="section-heading"><div><h2>Your game servers</h2><p>Choose Manage to edit each saved server record.</p></div><button class="button primary" id="workspaceAddServer">＋ Add server</button></div>' +
      (cachedServers.length ? '<div class="managed-server-grid">' + cachedServers.map(item => '<article class="managed-server"><div class="managed-server-top"><span class="game ' + gameClass(item.game) + '">' + gameLetter(item.game) + '</span><span class="server-status ' + statusClass(item.status) + '"><i></i>' + esc(item.status) + '</span></div><h3>' + esc(item.name) + '</h3><p>' + esc(item.game) + ' · ' + esc(item.panel) + '</p><div class="managed-server-id">ID · ' + esc(item.id) + '</div><div class="managed-server-actions"><button class="button secondary" data-manage-server="' + esc(item.id) + '">Manage server</button><button class="button danger" data-delete-server="' + esc(item.id) + '">Delete</button></div><small class="runtime-note">Runtime controls unavailable · host adapter required</small></article>').join("") + '</div>' : '<div class="empty-panel"><span>▣</span><h3>No servers yet</h3><p>Create your first server record to see it here.</p><button class="button primary" id="workspaceAddServer">＋ Create server</button></div>') + '</section>' +
      '<div class="notice-panel"><strong>Important:</strong> server records are saved in Nexus, but this version does not install game files or start/stop a real server process yet. That requires a host/runtime adapter.</div>';
  } else if (page === "Panel Connectors") {
    root.innerHTML = '<section class="card workspace-card"><div class="section-heading"><div><h2>Panel connections</h2><p>Stored endpoints, not yet authenticated.</p></div><button class="button primary" id="workspaceConnect">＋ Add connector</button></div><div class="workspace-connector-list">' +
      (cachedConnectors.length ? cachedConnectors.map(item => '<div class="workspace-connector"><div><strong>' + esc(item.panel_type) + '</strong><p>' + esc(item.base_url) + '</p><small>' + esc(item.status) + '</small></div><button class="button danger" data-delete-connector="' + esc(item.id) + '">Remove</button></div>').join("") : '<div class="empty-panel"><h3>No panel connections</h3><p>Add a Pterodactyl, Pelican or AMP endpoint.</p></div>') + '</div></section><div class="notice-panel">For safety, Nexus currently stores only the URL. It does not store API keys or send commands to external panels.</div>';
  } else {
    const content = {
      "Nodes & Capacity":["Node inventory","CPU, RAM, disk and allocation telemetry","No node agents are connected. This section will show real capacity after a node agent is added."],
      "Backups & Recovery":["Backup jobs","Policies, snapshots and restore points","No backup provider is configured. No backup has been created by Nexus."],
      "Store & Billing":["Products and plans","Plans, invoices and payment status","Billing is not connected. No payments or invoices are being processed."],
      "Customers & Resellers":["Customer accounts","Owners, customers, teams and resellers","Authentication and tenant permissions must be implemented before customer access is enabled."],
      "Automation & AI":["Workflow center","Scheduled tasks and event-driven automation","No automation runs in the background in this version."],
      "Extensions":["Extensions library","Approved add-ons and integrations","The extension loader and marketplace are not active yet."],
      "Security & Audit":["Activity audit","Recent changes recorded by this local workspace","The local activity feed is available on Overview. Owner login, sessions and role permissions are not yet implemented."],
      "Settings":["Workspace settings","Control how this Nexus workspace is presented","Workspace name is set during installation. More settings will be added as their backend support is implemented."]
    }[page] || ["Workspace","Nexus Panel","This section is not available yet."];
    root.innerHTML = '<section class="card workspace-card placeholder-workspace"><div class="placeholder-icon">✦</div><h2>' + esc(content[0]) + '</h2><p>' + esc(content[1]) + '</p><div class="notice-panel">' + esc(content[2]) + '</div></section>';
  }
}
function showPage(page) {
  currentPage = pages[page] ? page : "Overview";
  $$(".nav-link[data-page]").forEach(button => button.classList.toggle("active", button.dataset.page === currentPage));
  $("#breadcrumb").textContent = currentPage;
  const copy = pages[currentPage];
  $("#pageTitle").innerHTML = copy[0];
  $("#pageSubtitle").textContent = copy[1];
  $$(".overview-section").forEach(section => section.hidden = currentPage !== "Overview");
  renderPageWorkspace(currentPage);
  closeMenu();
}
$$("[data-page]").forEach(el => el.addEventListener("click", () => showPage(el.dataset.page)));
function openDialog() { const dialog = $("#connectDialog"); if (dialog.showModal) dialog.showModal(); else toast("Please use a modern browser."); }
$("#connect").addEventListener("click", openDialog);
$("#addServer").addEventListener("click", () => $("#serverDialog").showModal());
$("#addConnector").addEventListener("click", openDialog);
$("#closeDialog").addEventListener("click", () => $("#connectDialog").close());
$("#closeServerDialog").addEventListener("click", () => $("#serverDialog").close());
$("#closeManageServerDialog").addEventListener("click", () => $("#manageServerDialog").close());
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
    if (currentPage !== "Overview") renderPageWorkspace(currentPage);
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
    toast("Connector endpoint saved. Live connection is not enabled yet."); await refreshDashboard();
  } catch (error) { toast(error.message); }
});
$("#serverForm").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/servers",{method:"POST",body:JSON.stringify({name:$("#serverName").value.trim(),game:$("#serverGame").value,panel:$("#serverPanel").value,status:"Configured"})});
    $("#serverDialog").close(); $("#serverForm").reset(); toast("Server record created."); await refreshDashboard(); showPage("Game Servers");
  } catch (error) { toast(error.message); }
});
function openManageServer(id) {
  const item = cachedServers.find(server => server.id === id);
  if (!item) { toast("Server record not found. Refresh and try again."); return; }
  $("#manageServerId").value = item.id;
  $("#manageServerName").value = item.name;
  $("#manageServerGame").value = item.game;
  $("#manageServerPanel").value = item.panel;
  $("#manageServerStatus").value = item.status;
  $("#manageServerDialog").showModal();
}
$("#manageServerForm").addEventListener("submit", async event => {
  event.preventDefault();
  const id = $("#manageServerId").value;
  try {
    await api("/api/servers/" + encodeURIComponent(id), {method:"PUT",body:JSON.stringify({
      name:$("#manageServerName").value.trim(), game:$("#manageServerGame").value,
      panel:$("#manageServerPanel").value, status:$("#manageServerStatus").value
    })});
    $("#manageServerDialog").close(); toast("Server record updated."); await refreshDashboard();
  } catch (error) { toast(error.message); }
});
document.addEventListener("click", async event => {
  const target = event.target.closest("button");
  if (!target) return;
  if (target.dataset.manageServer) { openManageServer(target.dataset.manageServer); return; }
  if (target.id === "workspaceAddServer") { $("#serverDialog").showModal(); return; }
  if (target.id === "workspaceConnect") { openDialog(); return; }
  const serverId = target.dataset.deleteServer;
  const connectorId = target.dataset.deleteConnector;
  if (serverId) {
    if (!confirm("Delete this saved server record? This does not delete a real game server.")) return;
    try { await api("/api/servers/"+encodeURIComponent(serverId),{method:"DELETE"}); toast("Server record deleted."); await refreshDashboard(); } catch (error) { toast(error.message); }
  }
  if (connectorId) {
    if (!confirm("Remove this saved connector record? No remote panel will be changed.")) return;
    try { await api("/api/connectors/"+encodeURIComponent(connectorId),{method:"DELETE"}); toast("Connector record removed."); await refreshDashboard(); } catch (error) { toast(error.message); }
  }
});
$("#refresh").addEventListener("click", async () => { if (await refreshDashboard()) toast("Dashboard refreshed."); });
$("#notifications").addEventListener("click", () => toast("Notifications will be enabled with the event system."));
$("#activityOptions").addEventListener("click", () => showPage("Security & Audit"));
$("#profileMenu").addEventListener("click", () => showPage("Settings"));
$("#search").addEventListener("input", event => {
  const query = event.target.value.toLowerCase().trim();
  $$(".connector, #serverRows tr, .managed-server, .workspace-connector").forEach(row => { row.hidden = !!query && !row.innerText.toLowerCase().includes(query); });
});
$("#openMenu").addEventListener("click", openMenu); $("#closeMenu").addEventListener("click", closeMenu); $("#scrim").addEventListener("click", closeMenu);
document.addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#search").focus(); }
  if (event.key === "Escape") closeMenu();
});
refreshDashboard();