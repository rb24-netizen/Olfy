import { OlfyClient } from "/olfy-client.js";
const $ = id => document.getElementById(id);
const client = new OlfyClient({baseUrl:location.origin,mode:"simulation",timeoutMs:45000});
const esc = value => String(value ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let current = null, fragrances = [], selected = new Set(), busy = false, dirty = false;
function message(text, success=false) { $("message").textContent=text; $("message").className=`message${success?" success":""}`; $("message").hidden=false; }
function syncButtons() {
  const active = !!current?.active_scan;
  $("run-practice").disabled = busy || !current || !current.software_ready || active;
  $("lab-demo").disabled = busy || !current || active;
  $("save-plan").disabled = busy || !current || active || selected.size<2 || selected.size>5;
  $("download-diagnostics").disabled = !current;
  $("refresh").disabled = busy;
}
function renderStatus(data) {
  $("workspace-summary").textContent = data.software_ready ? "Your software is ready for practice. A missing sensor is expected while you wait." : "Some local software checks need attention before practice.";
  $("checks").innerHTML = data.checks.map(c=>`<div class="check ${esc(c.status)}"><span class="check-icon" aria-label="${esc(c.status)}">${c.status==="ready"?"✓":"!"}</span><b>${esc(c.label)}</b><small>${esc(c.detail)}</small></div>`).join("");
  $("perfume-count").textContent=data.catalogue.perfume_count;
  $("reference-count").textContent=data.catalogue.reference_count;
  $("real-count").textContent=data.real_scans;
  $("sensor-state").textContent=data.hardware.connected?"Connected":"Waiting";
  $("data-path").textContent=data.data_directory;
  $("disk-space").textContent=`${(data.free_bytes/(1024**3)).toFixed(1)} GB available on this disk. Back up regularly and keep the data folder when updating.`;
  $("version").textContent=`OLFY / SOFTWARE ${data.software_version}`;
  const diagnostics={software_version:data.software_version,software_ready:data.software_ready,system:data.system,packages:data.packages,checks:data.checks,data_directory:data.data_directory,free_bytes:data.free_bytes,real_scans:data.real_scans,simulation_scans:data.simulation_scans,catalogue:data.catalogue,hardware:{connected:data.hardware.connected,bme688_drivers_installed:data.hardware.bme688_drivers_installed,serial_driver_installed:data.hardware.serial_driver_installed},limits:data.limits};
  $("diagnostics").textContent=JSON.stringify(diagnostics,null,2);
  if(data.active_scan)message("A recording is running. Finish or abort it in the app before practice, plan changes or backup.");
  renderHardware();syncButtons();
}
async function refresh() {
  $("refresh").disabled=true;
  try { current=await client.request("setup");renderStatus(current); }
  catch(error){current=null;$("workspace-summary").textContent="Cannot reach the local backend. Keep Olfy running in Terminal, then refresh checks.";message(error.message);syncButtons();}
  finally {$("refresh").disabled=busy;}
}
function markDirty() {dirty=true;$("plan-badge").textContent="Unsaved changes";}
function estimate() {
  $("selected-count").textContent=`${selected.size} / 5 selected`;
  $("plan-estimate").textContent=selected.size>=2?`${selected.size} perfumes × 3 fresh exposures × 3 collection days, plus ${$("plan-unknown").checked?6:3} controls = ${selected.size*9+($("plan-unknown").checked?6:3)} planned recordings.`:"Pick at least two perfumes to see your collection plan.";
  syncButtons();
}
function renderFragrances() {
  const query=$("perfume-search").value.trim().toLowerCase();
  const found=fragrances.filter(f=>`${f.brand} ${f.name} ${f.concentration_label}`.toLowerCase().includes(query));
  $("perfume-options").innerHTML=found.length?found.map(f=>`<label class="perfume-choice"><input type="checkbox" value="${esc(f.fragrance_id)}" ${selected.has(f.fragrance_id)?"checked":""}><span><b>${esc(f.brand)}</b>${esc(f.name)}<small>${esc(f.concentration_label||"Check exact concentration on bottle")}</small></span></label>`).join(""):"<p class=\"micro\">No matching variant in this catalogue. Try another brand or perfume name.</p>";
}
function renderPlan(plan) {
  if(!plan)return;
  $("saved-plan").hidden=false;
  $("plan-badge").textContent=dirty?"Unsaved changes":"Plan saved";
  $("plan-description").textContent=`Saved: ${plan.fragrance_ids.length} perfume variants; planned collection dates ${plan.collection_days.join(", ")}. ${plan.fragrance_ids.length*9+3*plan.controls_per_day} recordings. The checklist remains editable; use actual dates and fresh samples.`;
}
function renderHardware() {
  const serial=$("hardware-adapter").value==="serial";
  const installed=!!current?.hardware[serial?"serial_driver_installed":"bme688_drivers_installed"];
  $("driver-badge").textContent=installed?"Drivers installed":"Optional until delivery";
  $("driver-status").textContent=installed?"The optional software packages are installed. The physical connection still needs testing.":"Install these optional drivers when you are ready. Practice works without them.";
  $("hardware-command").textContent=`bash start.sh --${serial?"serial":"hardware"} --setup`;
  $("connection-help").textContent=serial?"Connect a USB data cable to the board streaming newline-delimited Olfy JSON samples.":"BME688 breakout → QT cable → MCP2221 bridge → USB data cable → Mac.";
}
async function task(button,fn) {
  if(busy)return;
  busy=true;syncButtons();$("message").hidden=true;
  try{await fn();}
  catch(error){message(error.message);}
  finally{busy=false;await refresh();syncButtons();}
}
$("refresh").addEventListener("click",()=>{ $("message").hidden=true;refresh(); });
$("run-practice").addEventListener("click",()=>task($("run-practice"),async()=>{
  $("run-practice").textContent="Running the software pipeline…";
  $("practice-status").textContent="Generating temporary samples, training, checking predictions and restoring a backup…";
  $("practice-checks").hidden=true;
  try {
    const result=await client.request("practice",{data:{mode:"simulation"}});
    $("practice-checks").innerHTML=result.checks.map(c=>`<li class="${c.passed?"":"failed"}"><b>${esc(c.label)}</b><span>${esc(c.detail)}</span></li>`).join("");
    $("practice-checks").hidden=false;
    $("practice-status").textContent=result.passed?"Practice passed. All six software checks completed.":"Practice completed with checks needing attention.";
    message(result.passed?"Practice passed. Your workspaces were unchanged; no physical perfume was measured.":"A practice check needs attention. Review the steps below.",result.passed);
  }catch(error){$("practice-status").textContent="Practice did not complete. Your existing recordings remain in place. Refresh checks before retrying.";throw error;}
  finally{$("run-practice").innerHTML="Run full practice test <span>→</span>";}
}));
$("lab-demo").addEventListener("click",()=>task($("lab-demo"),async()=>{
  await client.loadDemo();location.href="/lab?mode=simulation&tab=dataset";
}));
$("perfume-search").addEventListener("input",renderFragrances);
$("perfume-options").addEventListener("change",event=>{
  const input=event.target;if(!(input instanceof HTMLInputElement))return;
  if(input.checked&&selected.size>=5){input.checked=false;message("Start with at most five perfume variants. All 50 remain available in Lab.");return;}
  if(input.checked)selected.add(input.value);else selected.delete(input.value);
  markDirty();estimate();
});
$("plan-unknown").addEventListener("change",()=>{markDirty();estimate();});
for(const id of ["plan-date","plan-substrate","plan-dose","plan-drydown"])$(id).addEventListener("input",markDirty);
$("plan-form").addEventListener("submit",event=>{
  event.preventDefault();task($("save-plan"),async()=>{
    const result=await client.request("plan",{data:{mode:"real",fragrance_ids:[...selected],start_date:$("plan-date").value,substrate:$("plan-substrate").value,dose:$("plan-dose").value,drydown_min:Number($("plan-drydown").value),include_unknown_control:$("plan-unknown").checked}});
    dirty=false;renderPlan(result.plan);message("Experiment plan saved. It is available in Lab and included in full data backups.",true);
  });
});
$("hardware-adapter").addEventListener("change",renderHardware);
$("copy-hardware").addEventListener("click",async()=>{
  try{await navigator.clipboard.writeText($("hardware-command").textContent);$("copy-hardware").textContent="Copied";}
  catch{message("Select and copy the command shown above, then paste it into Terminal in the project folder.");}
});
$("backup").addEventListener("click",event=>{
  if(current?.active_scan||busy){event.preventDefault();message("Finish or abort a running scan, and let practice complete, before downloading a backup.");}
});
$("download-diagnostics").addEventListener("click",()=>{
  const blob=new Blob([$("diagnostics").textContent],{type:"application/json"});
  const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="Olfy_Diagnostics.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function initialize(){
  await refresh();
  try{
    const catalogue=await client.catalogue();fragrances=catalogue.fragrances;
    if(current?.plan){const p=current.plan;selected=new Set(p.fragrance_ids);$("plan-date").value=p.start_date;$("plan-substrate").value=p.substrate;$("plan-dose").value=p.dose;$("plan-drydown").value=p.drydown_min;$("plan-unknown").checked=p.include_unknown_control??true;renderPlan(p);}
    renderFragrances();estimate();
  }catch(error){$("perfume-options").textContent="Catalogue unavailable. Reload this page after Olfy is running.";message(error.message);}
}
initialize();
