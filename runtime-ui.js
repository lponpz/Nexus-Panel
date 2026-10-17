(() => {
  const q = (s, root=document) => root.querySelector(s);
  let serverId = null, poll = null;
  const api = async (url, options={}) => {
    const method = String(options.method || "GET").toUpperCase();
    const headers = Object.assign({"Content-Type":"application/json"}, options.headers || {});
    if (["POST","PUT","PATCH","DELETE"].includes(method)) {
      const sr = await fetch("/api/auth/session", {credentials:"same-origin"});
      const session = await sr.json().catch(()=>({}));
      if (!session.authenticated) { location.replace("/login.html"); throw new Error("Please sign in again."); }
      headers["X-Nexus-CSRF"] = session.csrf_token;
    }
    const res = await fetch(url, Object.assign({},options,{credentials:"same-origin",headers}));
    const data = await res.json().catch(()=>({ok:false,error:"Invalid response"}));
    if (res.status === 401) { location.replace("/login.html"); throw new Error("Login required."); }
    if (!res.ok || data.ok === false) throw new Error(data.error || ("Request failed: " + res.status));
    return data;
  };
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const url = suffix => "/api/servers/" + encodeURIComponent(serverId) + suffix;
  const style = document.createElement("style");
  style.textContent = ".nx-tools{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.nx-tools button{border:1px solid #31577a;background:#112942;color:#b9ddff;border-radius:8px;padding:8px 11px;cursor:pointer}.nx-overlay{position:fixed;inset:0;background:#030914dd;z-index:9999;display:flex;align-items:center;justify-content:center;padding:14px}.nx-modal{width:min(980px,100%);max-height:92vh;overflow:auto;background:#0b1726;border:1px solid #31506e;border-radius:16px;padding:18px;color:#edf5ff;box-shadow:0 20px 80px #0009}.nx-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.nx-head button,.nx-action{border:1px solid #31577a;background:#112942;color:#b9ddff;border-radius:8px;padding:9px 12px;cursor:pointer}.nx-console{background:#030912;border:1px solid #20364e;border-radius:10px;color:#b9f7d3;padding:12px;height:48vh;overflow:auto;white-space:pre-wrap;font:12px ui-monospace,monospace}.nx-row{display:flex;gap:8px;margin-top:10px}.nx-row input{flex:1;min-width:0;background:#07111f;border:1px solid #29445e;color:#fff;border-radius:8px;padding:10px}.nx-files{display:flex;flex-direction:column;gap:7px;margin-top:12px}.nx-file{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:10px;border:1px solid #20364e;border-radius:8px}.nx-muted{color:#8ea5be;font-size:12px}.nx-editor{width:100%;min-height:240px;background:#030912;color:#d9edff;border:1px solid #29445e;border-radius:8px;padding:10px;box-sizing:border-box}";
  document.head.appendChild(style);
  function showModal(title, body) {
    const overlay=document.createElement("div"); overlay.className="nx-overlay";
    overlay.innerHTML='<div class="nx-modal"><div class="nx-head"><div><h2 style="margin:0 0 5px">'+esc(title)+'</h2><div class="nx-muted">Nexus local server runtime</div></div><button type="button" data-nx-close>Close</button></div><div style="margin-top:15px">'+body+'</div></div>';
    overlay.addEventListener("click", e=>{if(e.target===overlay||e.target.closest("[data-nx-close]")){overlay.remove();if(poll)clearInterval(poll);}});
    document.body.appendChild(overlay); return overlay;
  }
  async function openConsole(id, name) {
    serverId=id;
    const overlay=showModal(name+" — Console",'<div class="nx-tools"><button data-nx-start>Start</button><button data-nx-stop>Stop</button><button data-nx-refresh>Refresh</button><span class="nx-muted" data-nx-state>Checking process…</span></div><pre class="nx-console" data-nx-output>Loading logs…</pre><form class="nx-row" data-nx-command><input maxlength="1000" placeholder="Enter game console command…" required><button class="nx-action">Send</button></form><div class="nx-row"><input data-launch value="java -Xms1G -Xmx2G -jar server.jar nogui" maxlength="500"><button class="nx-action" data-save-launch>Save launch command</button></div><p class="nx-muted">Java server only in this runtime adapter. Upload server.jar in the server folder first. Owner login is enabled; keep the forwarded port private until node isolation and deployment hardening are complete.</p>');
    const output=q("[data-nx-output]",overlay), state=q("[data-nx-state]",overlay);
    async function refresh(){try{const d=await api(url("/console"));output.textContent=(d.logs||[]).map(x=>"["+x.time+"] "+x.text).join("\n")||"No logs yet.";output.scrollTop=output.scrollHeight;state.textContent=d.running?"Running":"Stopped";}catch(e){output.textContent=e.message;}}
    q("[data-nx-start]",overlay).onclick=async()=>{try{await api(url("/start"),{method:"POST",body:JSON.stringify({launch_command:q("[data-launch]",overlay).value})});await refresh();}catch(e){state.textContent=e.message;}};
    q("[data-save-launch]",overlay).onclick=async()=>{try{await api(url("/configure"),{method:"POST",body:JSON.stringify({launch_command:q("[data-launch]",overlay).value})});alert("Launch command saved.");}catch(e){alert(e.message);}};
    api(url("")).then(d=>{if(d.launch_command)q("[data-launch]",overlay).value=d.launch_command;}).catch(()=>{});
    q("[data-nx-stop]",overlay).onclick=async()=>{try{await api(url("/stop"),{method:"POST",body:"{}"});await refresh();}catch(e){state.textContent=e.message;}};
    q("[data-nx-refresh]",overlay).onclick=refresh;
    q("[data-nx-command]",overlay).onsubmit=async e=>{e.preventDefault();const input=q("input",e.currentTarget);try{await api(url("/command"),{method:"POST",body:JSON.stringify({command:input.value})});input.value="";await refresh();}catch(err){state.textContent=err.message;}};
    await refresh();poll=setInterval(refresh,2000);
  }
  async function openFiles(id,name) {
    serverId=id;let currentPath="";
    const overlay=showModal(name+" — Files",'<div class="nx-tools"><button data-up>Up</button><button data-folder>New folder</button><button data-text>New text file</button><button data-upload>Upload file</button><input data-upload-input type="file" hidden><button data-refresh>Refresh</button></div><div class="nx-muted" data-path></div><div class="nx-files" data-list>Loading…</div><div data-editor-wrap hidden><h3 data-editor-title>Edit file</h3><textarea class="nx-editor" data-editor></textarea><div class="nx-tools"><button data-save>Save</button><button data-cancel>Cancel</button></div></div><p class="nx-muted">Basic text editing only; binary uploads and downloads are not available yet.</p>');
    const list=q("[data-list]",overlay), pathLabel=q("[data-path]",overlay), editorWrap=q("[data-editor-wrap]",overlay), editor=q("[data-editor]",overlay);
    let editPath=null;
    async function refresh(){pathLabel.textContent="/"+currentPath;try{const d=await api(url("/files?path="+encodeURIComponent(currentPath)));list.innerHTML=(d.items||[]).map(x=>'<div class="nx-file"><button class="nx-action" data-open="'+esc(x.name)+'" data-dir="'+(x.directory?"1":"0")+'">'+(x.directory?"📁 ":"📄 ")+esc(x.name)+'</button><span class="nx-muted">'+(x.directory?"Folder":String(x.size)+" bytes")+'</span><button class="nx-action" data-delete="'+esc(x.name)+'">Delete</button></div>').join("")||'<p class="nx-muted">Folder is empty.</p>';}catch(e){list.textContent=e.message;}}
    list.onclick=async e=>{const b=e.target.closest("button");if(!b)return;const name=b.dataset.open||b.dataset.delete;if(!name)return;const p=currentPath?currentPath+"/"+name:name;if(b.dataset.dir==="1"){currentPath=p;await refresh();return;}if(b.dataset.open){try{const d=await api(url("/file-content?path="+encodeURIComponent(p)));editPath=p;editor.value=d.content||"";q("[data-editor-title]",overlay).textContent="Edit "+p;editorWrap.hidden=false;}catch(err){alert(err.message);}return;}if(b.dataset.delete&&confirm("Delete "+p+"?")){try{await api(url("/files"),{method:"POST",body:JSON.stringify({operation:"delete",path:p})});await refresh();}catch(err){alert(err.message);}}};
    q("[data-refresh]",overlay).onclick=refresh;
    q("[data-up]",overlay).onclick=()=>{currentPath=currentPath.split("/").slice(0,-1).join("/");refresh();};
    q("[data-folder]",overlay).onclick=async()=>{const n=prompt("Folder name");if(!n||n.includes("/")||n.includes("\\"))return;try{await api(url("/files"),{method:"POST",body:JSON.stringify({operation:"mkdir",path:currentPath?currentPath+"/"+n:n})});await refresh();}catch(e){alert(e.message);}};
    q("[data-upload]",overlay).onclick=()=>q("[data-upload-input]",overlay).click();
    q("[data-upload-input]",overlay).onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>50*1024*1024){alert("Maximum upload size is 50 MB.");return;}try{const target=url("/file-upload?name="+encodeURIComponent(file.name)+"&path="+encodeURIComponent(currentPath));const sessionResponse=await fetch("/api/auth/session",{credentials:"same-origin"});const session=await sessionResponse.json();if(!session.authenticated){location.replace("/login.html");throw new Error("Please sign in again.");}const response=await fetch(target,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/octet-stream","X-Nexus-CSRF":session.csrf_token},body:file});const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||"Upload failed");await refresh();}catch(err){alert(err.message);}e.target.value="";};
    q("[data-text]",overlay).onclick=()=>{const n=prompt("Text file name (e.g. notes.txt)");if(!n||n.includes("/")||n.includes("\\"))return;editPath=currentPath?currentPath+"/"+n:n;editor.value="";q("[data-editor-title]",overlay).textContent="Create "+editPath;editorWrap.hidden=false;};
    q("[data-save]",overlay).onclick=async()=>{if(!editPath)return;try{await api(url("/files"),{method:"POST",body:JSON.stringify({operation:"write",path:editPath,content:editor.value})});editPath=null;editorWrap.hidden=true;await refresh();}catch(e){alert(e.message);}};
    q("[data-cancel]",overlay).onclick=()=>{editPath=null;editorWrap.hidden=true;};
    await refresh();
  }
  function attachTools(){
    document.querySelectorAll(".managed-server").forEach(card=>{
      if(card.querySelector(".nx-tools"))return;
      const title=card.querySelector("h3")?.textContent||"Server";
      const manage=card.querySelector("[data-manage-server]");
      const id=manage?.dataset.manageServer || card.querySelector("[data-delete-server]")?.dataset.deleteServer;
      if(!id)return;
      const bar=document.createElement("div");bar.className="nx-tools";
      const consoleBtn=document.createElement("button");consoleBtn.textContent="Open Console";consoleBtn.onclick=()=>openConsole(id,title);
      const filesBtn=document.createElement("button");filesBtn.textContent="File Manager";filesBtn.onclick=()=>openFiles(id,title);
      bar.append(consoleBtn,filesBtn);card.appendChild(bar);
    });
  }
  new MutationObserver(attachTools).observe(document.body,{childList:true,subtree:true});
  attachTools();
})();