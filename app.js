const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const toast = message => { const el = $("#toast"); el.textContent = message; el.classList.add("show"); clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => el.classList.remove("show"), 3500); };
const pages = {
  "Overview":["Your hosting, <span>in one place.</span>","A unified command center for your saved game hosting records."],
  "Game Servers":["Every server, <span>one view.</span>","Open a server console, run game commands, upload files and edit its saved settings."],
  "Panel Connectors":["Connect your <span>hosting world.</span>","Review saved endpoints. Live authentication and external panel control still require adapters."],
  "Nodes & Capacity":["Capacity without <span>guesswork.</span>","Node telemetry appears here once a real node agent is implemented."],
  "Backups & Recovery":["Recovery you can <span>trust.</span>","Backup policies and restore operations need a configured storage provider."],
  "Store & Billing":["Your hosting <span>business center.</span>","Manage hosting plans, create invoices and record verified offline payments."],
  "Customers & Resellers":["Every tenant, <span>properly separated.</span>","Customer accounts and role-based tenant access are not implemented yet."],
  "Automation & AI":["Less repetition. <span>More control.</span>","Create safe workflows here in a later phase; no background jobs run yet."],
  "Extensions":["Make Nexus <span>your own.</span>","Manage add-ons here when the extension system is available."],
  "Security & Audit":["Security with <span>visibility.</span>","Review locally recorded changes and owner session controls."],
  "Settings":["Tune your <span>workspace.</span>","Workspace and integration settings."]
};
let currentPage = "Overview";
let cachedServers = [];
let cachedConnectors = [];
function closeMenu(){ $("#sidebar").classList.remove("open"); $("#scrim").classList.remove("show"); }
function openMenu(){ $("#sidebar").classList.add("open"); $("#scrim").classList.add("show"); }
async function api(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = {"Content-Type":"application/json", ...(options.headers || {})};
  if (["POST","PUT","PATCH","DELETE"].includes(method) && path !== "/api/setup" && path !== "/api/auth/login") {
    const sessionResponse = await fetch("/api/auth/session", {credentials:"same-origin"});
    const session = await sessionResponse.json().catch(() => ({}));
    if (!session.authenticated) { location.replace("/login.html"); throw new Error("Please sign in again."); }
    headers["X-Nexus-CSRF"] = session.csrf_token;
  }
  const response = await fetch(path, {...options, credentials:"same-origin", headers});
  const data = await response.json().catch(() => ({ok:false,error:"Server returned an invalid response"}));
  if (response.status === 401) { location.replace("/login.html"); throw new Error("Login required."); }
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
    items.map(item => '<tr data-search="' + esc([item.name,item.game,item.panel,item.connect_address].join(" ").toLowerCase()) + '">' +
      '<td><div class="server-name"><span class="game ' + gameClass(item.game) + '">' + gameLetter(item.game) + '</span><div><strong>' + esc(item.name) + '</strong><small>' + esc(item.id.slice(0,8)) + '</small></div></div></td>' +
      '<td>' + esc(item.game) + '</td><td><span class="tag">' + esc(item.panel) + '</span></td>' +
      '<td><span class="server-status ' + statusClass(item.status) + '"><i></i>' + esc(item.status) + '</span></td>' +
      '<td>' + (item.connect_address ? '<button class="address-copy" data-copy-address="' + esc(item.connect_address) + '">' + esc(item.connect_address) + '</button><small class="address-hint">' + (item.public_address_configured ? 'Public address set' : 'Local only · configure public IP') + '</small>' : '<span>Address unavailable for this adapter</span>') + '</td><td><button class="record-manage" data-manage-server="' + esc(item.id) + '">Manage</button></td></tr>').join("");
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
    root.innerHTML = '<section class="card workspace-card"><div class="section-heading"><div><h2>Your game servers</h2><p>Use Console and File Manager for each server. Java runtime currently supports Java server JARs.</p></div><button class="button primary" id="workspaceAddServer">＋ Add server</button></div>' +
      '<section class="network-address-panel"><div><h3>Public Minecraft address</h3><p>Set the public IP or DNS name of the machine that runs these game servers.</p></div><form id="publicHostForm" class="public-host-form"><input id="publicHostInput" maxlength="253" placeholder="e.g. 203.0.113.10 or mc.example.com" aria-label="Public IP or hostname"><button class="button secondary" type="submit">Save address</button></form><small id="publicHostStatus">Loading network settings…</small></section>' +
      (cachedServers.length ? '<div class="managed-server-grid">' + cachedServers.map(item => '<article class="managed-server"><div class="managed-server-top"><span class="game ' + gameClass(item.game) + '">' + gameLetter(item.game) + '</span><span class="server-status ' + statusClass(item.status) + '"><i></i>' + esc(item.status) + '</span></div><h3>' + esc(item.name) + '</h3><p>' + esc(item.game) + ' · ' + esc(item.panel) + '</p>' + (item.connect_address ? '<div class="server-address-card"><small>JOIN ADDRESS · ' + esc(item.connection_type || 'Game') + '</small><strong>' + esc(item.connect_address) + '</strong><button class="button secondary" data-copy-address="' + esc(item.connect_address) + '">Copy IP</button><small>' + (item.public_address_configured ? 'Public address configured' : 'LOCAL ONLY — set your public IP above') + '</small></div>' : '') + '<div class="managed-server-id">ID · ' + esc(item.id) + '</div><div class="managed-server-actions"><button class="button secondary" data-manage-server="' + esc(item.id) + '">Manage server</button><button class="button danger" data-delete-server="' + esc(item.id) + '">Delete</button></div><small class="runtime-note">' + (item.game === 'Minecraft' && item.connect_port ? 'Java Edition · TCP port ' + esc(item.connect_port) + ' · Paper installer available' : 'Runtime adapter needed for this game') + '</small></article>').join("") + '</div>' : '<div class="empty-panel"><span>▣</span><h3>No servers yet</h3><p>Create your first Minecraft server and Nexus will reserve a unique game port.</p><button class="button primary" id="workspaceAddServer">＋ Create server</button></div>') + '</section>' +
      '<div class="notice-panel"><strong>Joinability:</strong> each locally managed Minecraft server receives a unique TCP port. Install Paper, accept the EULA, start it, set the public IP/domain above, and allow that port through the host/cloud firewall and router. A displayed IP alone cannot bypass network restrictions. FiveM/Terraria runtimes are not enabled yet.</div>' +
      '<div class="notice-panel"><strong>Important:</strong> Nexus can launch a local Java server process, show console output, send game commands, and manage files after you upload server.jar. Remote node agents, resource telemetry, and production multi-user security still need implementation.</div>';
    loadNetworkAddress(root);
  } else if (page === "Panel Connectors") {
    root.innerHTML = '<section class="card workspace-card"><div class="section-heading"><div><h2>Panel connections</h2><p>Stored endpoints, not yet authenticated.</p></div><button class="button primary" id="workspaceConnect">＋ Add connector</button></div><div class="workspace-connector-list">' +
      (cachedConnectors.length ? cachedConnectors.map(item => '<div class="workspace-connector"><div><strong>' + esc(item.panel_type) + '</strong><p>' + esc(item.base_url) + '</p><small>' + esc(item.status) + '</small></div><button class="button danger" data-delete-connector="' + esc(item.id) + '">Remove</button></div>').join("") : '<div class="empty-panel"><h3>No panel connections</h3><p>Add a Pterodactyl, Pelican or AMP endpoint.</p></div>') + '</div></section><div class="notice-panel">For safety, Nexus currently stores only the URL. It does not store API keys or send commands to external panels.</div>';
  } else if (page === "Store & Billing") {
    root.innerHTML = '<section class="card workspace-card"><div class="section-heading"><div><h2>Hosting plans</h2><p>Create real plan records with monthly/yearly pricing and resource limits.</p></div></div><form id="billingPlanForm" class="billing-form"><label>Plan name<input name="name" maxlength="80" required placeholder="Starter"></label><label>Description<input name="description" maxlength="500" placeholder="For small communities"></label><div class="billing-fields"><label>Currency<select name="currency"><option>PKR</option><option>USD</option><option>INR</option></select></label><label>Price (whole currency units)<input name="price" type="number" min="0" max="1000000" value="500" required></label><label>Interval<select name="interval"><option value="month">Monthly</option><option value="year">Yearly</option></select></label><label>RAM (MB)<input name="ram" type="number" min="256" max="1048576" value="2048" required></label><label>CPU allocation (%)<input name="cpu" type="number" min="10" max="6400" value="100" required></label><label>Disk (MB)<input name="disk" type="number" min="512" max="1048576" value="10240" required></label><label>Server limit<input name="limit" type="number" min="1" max="100" value="1" required></label></div><button class="button primary" type="submit">Create hosting plan</button></form><div id="billingPlanList" class="billing-list">Loading plans…</div></section><section class="card workspace-card"><div class="section-heading"><div><h2>Invoices</h2><p>Create invoices against enabled plans and record offline payments.</p></div></div><form id="billingInvoiceForm" class="billing-form"><label>Plan<select name="plan_id" id="billingInvoicePlan" required><option value="">Loading plans…</option></select></label><label>Customer name<input name="customer_name" maxlength="120" required></label><label>Customer email<input name="customer_email" type="email" maxlength="254" required></label><button class="button primary" type="submit">Create invoice</button></form><div id="billingInvoiceList" class="billing-list">Loading invoices…</div><div class="notice-panel"><strong>Payment safety:</strong> this version tracks invoices and manual payment references only. It does not accept online payments or automatically provision servers after payment. A verified payment gateway and customer account system are still required.</div></section>';
    loadBillingWorkspace(root);
  } else {
    if (page === "Nodes & Capacity") {
      root.innerHTML = '<section class="card workspace-card"><div class="section-heading"><div><h2>Local host capacity</h2><p>Live operating-system metrics for the machine running this Nexus instance.</p></div><button class="button secondary" id="refreshHostMetrics">↻ Refresh metrics</button></div><div class="managed-server-grid" data-host-metrics><article class="managed-server"><h3>Loading telemetry…</h3><p>Reading CPU, memory and disk statistics.</p></article></div><div class="notice-panel">These are host-level readings, not per-container quotas. Remote nodes, container isolation and enforced resource limits are not implemented yet.</div></section>';
      const loadHostMetrics = async () => {
        const target = root.querySelector("[data-host-metrics]");
        try {
          const m = await api("/api/host-metrics");
          const memoryUsed = m.memory_total_mb == null || m.memory_available_mb == null ? null : Math.max(0, m.memory_total_mb - m.memory_available_mb);
          target.innerHTML = [
            ["CPU cores", String(m.cpu_count), "1-minute load: " + (m.load_1m == null ? "Unavailable" : m.load_1m)],
            ["Memory used", memoryUsed == null ? "Unavailable" : memoryUsed.toLocaleString() + " MB", "Total: " + (m.memory_total_mb == null ? "Unavailable" : m.memory_total_mb.toLocaleString() + " MB")],
            ["Disk free", m.disk_free_gb.toFixed(2) + " GB", "Total: " + m.disk_total_gb.toFixed(2) + " GB"]
          ].map(item => '<article class="managed-server"><div class="managed-server-top"><span class="game mc">N</span><span class="server-status configured"><i></i>Live</span></div><h3>' + esc(item[0]) + '</h3><p>' + esc(item[1]) + '</p><div class="managed-server-id">' + esc(item[2]) + '</div></article>').join("");
        } catch (error) { target.innerHTML = '<div class="notice-panel">' + esc(error.message) + '</div>'; }
      };
      root.querySelector("#refreshHostMetrics").addEventListener("click", loadHostMetrics);
      loadHostMetrics();
      return;
    }
    const content = {
      "Nodes & Capacity":["Node inventory","CPU, RAM, disk and allocation telemetry","No node agents are connected. This section will show real capacity after a node agent is added."],
      "Backups & Recovery":["Backup jobs","Per-server local backup and restore controls","Open a server's File Manager to create backups, schedule automatic snapshots, or restore a checksum-verified backup."],
      "Store & Billing":["Products and plans","Plans, invoices and payment status","Billing is not connected. No payments or invoices are being processed."],
      "Customers & Resellers":["Customer accounts","Owners, customers, teams and resellers","Owner login is active. Multi-user accounts, customer tenancy and per-server permissions remain to be implemented."],
      "Automation & AI":["Workflow center","Scheduled tasks and event-driven automation","No automation runs in the background in this version."],
      "Extensions":["Extensions library","Approved add-ons and integrations","The extension loader and marketplace are not active yet."],
      "Security & Audit":["Activity audit","Recent changes recorded by this local workspace","Owner login, expiring sessions, login throttling and CSRF-protected mutations are active. Customer roles and full production security hardening remain pending."],
      "Settings":["Workspace settings","Control how this Nexus workspace is presented","Workspace name is set during installation. More settings will be added as their backend support is implemented."]
    }[page] || ["Workspace","Nexus Panel","This section is not available yet."];
    root.innerHTML = '<section class="card workspace-card placeholder-workspace"><div class="placeholder-icon">✦</div><h2>' + esc(content[0]) + '</h2><p>' + esc(content[1]) + '</p><div class="notice-panel">' + esc(content[2]) + '</div></section>';
  }
}
async function loadNetworkAddress(root) {
  const form = root.querySelector("#publicHostForm");
  if (!form) return;
  const input = root.querySelector("#publicHostInput");
  const status = root.querySelector("#publicHostStatus");
  try {
    const d = await api("/api/network/public-host");
    input.value = d.public_host || "";
    status.textContent = d.configured
      ? "Public address set. Configure firewall/router rules for each allocated TCP port."
      : "No public host set. 127.0.0.1 addresses work only on the same machine.";
    if (d.environment_override) { input.disabled = true; form.querySelector("button").disabled = true; status.textContent = "Public host is configured by NEXUS_PUBLIC_HOST in the environment."; }
  } catch (error) { status.textContent = error.message; }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const saved = await api("/api/network/public-host", {method:"POST",body:JSON.stringify({public_host:input.value.trim()})});
      toast(saved.configured ? "Public game address saved." : "Public address cleared.");
      await refreshDashboard();
      loadNetworkAddress($("#pageWorkspace"));
    } catch (error) { toast(error.message); }
  }, {once:true});
}
async function loadBillingWorkspace(root) {
  const plansRoot = root.querySelector("#billingPlanList");
  const invoicesRoot = root.querySelector("#billingInvoiceList");
  const planSelect = root.querySelector("#billingInvoicePlan");
  try {
    const [plansData, invoicesData] = await Promise.all([api("/api/billing/plans"), api("/api/billing/invoices")]);
    const plans = plansData.items, invoices = invoicesData.items;
    if (!root.isConnected || !root.querySelector("#billingPlanForm")) return;
    plansRoot.innerHTML = plans.length ? plans.map(p => '<article class="billing-row"><div><strong>' + esc(p.name) + '</strong><p>' + esc(p.description || "Hosting plan") + '</p><small>' + esc(p.ram_mb) + ' MB RAM · ' + esc(p.cpu_percent) + '% CPU allocation · ' + esc(p.disk_mb) + ' MB disk · ' + esc(p.server_limit) + ' server(s)</small></div><div class="billing-price"><strong>' + esc(p.currency) + ' ' + (p.price_minor / 100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}) + '</strong><small>per ' + esc(p.billing_interval) + ' · ' + (p.enabled ? 'Enabled' : 'Disabled') + '</small><button class="button secondary" data-disable-plan="' + esc(p.id) + '" ' + (p.enabled ? '' : 'disabled') + '>Disable</button></div></article>').join("") : '<div class="empty-panel"><h3>No hosting plans yet</h3><p>Create a plan above.</p></div>';
    const enabled = plans.filter(p => p.enabled);
    planSelect.innerHTML = enabled.length ? '<option value="">Choose a plan</option>' + enabled.map(p => '<option value="' + esc(p.id) + '">' + esc(p.name) + ' — ' + esc(p.currency) + ' ' + (p.price_minor/100).toFixed(2) + ' / ' + esc(p.billing_interval) + '</option>').join("") : '<option value="">Create an enabled plan first</option>';
    invoicesRoot.innerHTML = invoices.length ? invoices.map(i => '<article class="billing-row"><div><strong>' + esc(i.invoice_number) + ' · ' + esc(i.plan_name) + '</strong><p>' + esc(i.customer_name) + ' · ' + esc(i.customer_email) + '</p><small>Due ' + esc(new Date(i.due_at).toLocaleDateString()) + (i.payment_reference ? ' · Reference: ' + esc(i.payment_reference) : '') + '</small></div><div class="billing-price"><strong>' + esc(i.currency) + ' ' + (i.amount_minor/100).toFixed(2) + '</strong><small class="billing-status ' + esc(i.status) + '">' + esc(i.status.toUpperCase()) + '</small>' + (i.status !== 'paid' ? '<button class="button secondary" data-record-payment="' + esc(i.id) + '">Record offline payment</button>' : '') + '</div></article>').join("") : '<div class="empty-panel"><h3>No invoices yet</h3><p>Create one using the form above.</p></div>';
  } catch (error) {
    if (plansRoot) plansRoot.innerHTML = '<div class="notice-panel">' + esc(error.message) + '</div>';
    if (invoicesRoot) invoicesRoot.innerHTML = '<div class="notice-panel">' + esc(error.message) + '</div>';
  }
}
document.addEventListener("submit", async event => {
  if (event.target.id === "billingPlanForm") {
    event.preventDefault();
    const f = new FormData(event.target);
    const amount = Number(f.get("price"));
    if (!Number.isFinite(amount) || amount < 0 || amount > 1000000) { toast("Invalid plan price."); return; }
    try {
      await api("/api/billing/plans", {method:"POST", body:JSON.stringify({
        name:f.get("name"), description:f.get("description"), currency:f.get("currency"),
        price_minor:Math.round(amount*100), billing_interval:f.get("interval"),
        ram_mb:Number(f.get("ram")), cpu_percent:Number(f.get("cpu")),
        disk_mb:Number(f.get("disk")), server_limit:Number(f.get("limit"))
      })});
      toast("Hosting plan created."); await loadBillingWorkspace($("#pageWorkspace"));
    } catch(error) { toast(error.message); }
  }
  if (event.target.id === "billingInvoiceForm") {
    event.preventDefault();
    const f = new FormData(event.target);
    try {
      await api("/api/billing/invoices", {method:"POST", body:JSON.stringify({
        plan_id:f.get("plan_id"), customer_name:f.get("customer_name"), customer_email:f.get("customer_email")
      })});
      event.target.reset(); toast("Invoice created."); await loadBillingWorkspace($("#pageWorkspace"));
    } catch(error) { toast(error.message); }
  }
});
document.addEventListener("click", async event => {
  const disable = event.target.closest("[data-disable-plan]");
  if (disable) {
    if (!confirm("Disable this plan? Existing invoices will remain unchanged.")) return;
    try { await api("/api/billing-plans/" + encodeURIComponent(disable.dataset.disablePlan), {method:"DELETE"}); toast("Plan disabled."); await loadBillingWorkspace($("#pageWorkspace")); }
    catch(error) { toast(error.message); }
  }
  const record = event.target.closest("[data-record-payment]");
  if (record) {
    const reference = prompt("Enter the verified offline payment reference (bank/Easypaisa/JazzCash receipt ID):");
    if (!reference || !reference.trim()) return;
    const notes = prompt("Optional note (e.g. who verified it):") || "";
    try { await api("/api/billing/invoices/" + encodeURIComponent(record.dataset.recordPayment) + "/record-payment", {method:"POST", body:JSON.stringify({payment_reference:reference.trim(),notes})}); toast("Manual payment reference recorded. No game server was provisioned."); await loadBillingWorkspace($("#pageWorkspace")); }
    catch(error) { toast(error.message); }
  }
});
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
    const created = await api("/api/servers",{method:"POST",body:JSON.stringify({name:$("#serverName").value.trim(),game:$("#serverGame").value,panel:$("#serverPanel").value,status:"Configured"})});
    $("#serverDialog").close(); $("#serverForm").reset(); toast(created.item.connect_address ? "Server created. Join address: " + created.item.connect_address : "Server record created."); await refreshDashboard(); showPage("Game Servers");
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
  if (target.dataset.copyAddress) {
    try { await navigator.clipboard.writeText(target.dataset.copyAddress); toast("Join address copied: " + target.dataset.copyAddress); }
    catch (error) { window.prompt("Copy this game address:", target.dataset.copyAddress); }
    return;
  }
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
$("#profileMenu").addEventListener("click", async () => {
  if (!confirm("Sign out of Nexus Panel?")) return;
  try { await api("/api/auth/logout", {method:"POST", body:"{}"}); location.replace("/login.html"); }
  catch (error) { toast(error.message); }
});
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