"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct = value => value == null ? "Not tested" : `${Math.round(value * 100)}%`;
let mode = "simulation", state = null, selectedScan = null, refreshing = false, datasetSignature = "", modelSignature = "";
let catalogue = null, catalogueSignature = "";
let readiness = null, readinessSignature = "";
let historySignature = "";
let plannedRows = [];
const form = $("capture-form");
const date = new Date();
form.elements.group_id.value = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;

function showError(message) { $("error").textContent = message; $("error").hidden = false; }
function tab(name) {
  for (const node of document.querySelectorAll(".tab")) node.hidden = node.id !== `${name}-tab`;
  for (const node of document.querySelectorAll(".nav")) node.classList.toggle("active", node.dataset.tab === name);
  $("page-title").textContent = {record:"Capture a response.",dataset:"A library of fingerprints.",catalogue:"A reference for every perfume.",model:"Learn. Compare. Test."}[name];
}
for (const node of document.querySelectorAll(".nav")) node.addEventListener("click", () => tab(node.dataset.tab));

async function api(path, data) {
  path = path.replace(/^\/api\/(?!v1\/)/, "/api/v1/");
  const options = data === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-Olfy-Token":state?.csrf_token || ""},body:JSON.stringify({...data,mode})};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

async function action(button, fn) {
  $("error").hidden = true;
  button.disabled = true;
  try { await fn(); await refresh(true); }
  catch (error) { showError(error.message); }
  finally { button.disabled = false; if (state) renderRecorder(state.recorder); }
}

async function setMode(next, {recover = false} = {}) {
  if (next === mode) return;
  if (state?.recorder.active && !recover) return showError("Finish or abort the current recording before switching workspaces.");
  mode = next; selectedScan = null; state = null; datasetSignature = modelSignature = "";
  readiness = null; readinessSignature = "";
  historySignature = "";
  $("scan-detail").hidden = true; $("prediction").replaceChildren();
  $("simulation-mode").classList.toggle("selected", mode === "simulation");
  $("real-mode").classList.toggle("selected", mode === "real");
  const banner = $("mode-banner"); banner.className = `notice ${mode}`;
  banner.innerHTML = mode === "simulation" ? "<b>SIMULATION</b><span>Artificial signals. Results test the software only.</span>" : "<b>REAL SENSOR</b><span>Measured data only. Hardware connection still needs verification on your device.</span>";
  $("hardware-setup").hidden = $("real-fields").hidden = mode !== "real";
  $("catalogue-select-field").hidden = mode !== "real";
  $("planned-sample-field").hidden = mode !== "real" || !plannedRows.length;
  $("seed-demo").hidden = mode !== "simulation";
  if (mode === "simulation" && form.elements.fragrance_id.value) {
    form.elements.fragrance_id.value = "";
    form.elements.label.value = "Demo A";
    form.elements.label.readOnly = false;
  }
  if (mode === "real" && form.elements.label.value.startsWith("Demo ")) form.elements.label.value = "";
  form.elements.label.placeholder = mode === "real" ? "e.g. Tom Ford Oud Wood EDP" : "Demo A";
  if (mode === "simulation" && !form.elements.label.value) form.elements.label.value = "Demo A";
  $("export").href = `/api/v1/export?mode=${mode}`;
  $("error").hidden = true;
  await refresh(true);
  if(mode === "real") await loadDevices();
}
$("simulation-mode").addEventListener("click", () => setMode("simulation"));
$("real-mode").addEventListener("click", () => setMode("real"));
$("seed-demo").addEventListener("click", () => action($("seed-demo"), async () => { await api("/api/seed", {}); tab("dataset"); }));
$("connect").addEventListener("click", () => action($("connect"), async () => {
  const adapter_id = $("sensor-adapter").value;
  const config = adapter_id === "serial" ? {port:$("serial-port").value || "auto",baud_rate:Number($("baud-rate").value)} : {address:$("sensor-address").value || "auto",device_id:form.elements.device_id.value.trim()};
  await api("/api/connect", {adapter_id,config});
}));
async function loadDevices() {
  try {
    const found = await api("/api/adapters");
    const ports = found.serial_ports.filter(p=>p.usb);
    updateSelect($("serial-port"),[["auto","Auto USB port"],...ports.map(p=>[p.port,`${p.port} · ${p.description}`])]);
    $("discovery-state").textContent=`${found.usb_bridges.length} MCP2221 bridge(s) · ${ports.length} USB serial port(s). ${found.warnings.join(" ")}`;
  } catch(error) { showError(error.message); }
}
$("refresh-devices").addEventListener("click", () => action($("refresh-devices"),loadDevices));
$("sensor-adapter").addEventListener("change", () => {
  $("serial-options").hidden = $("sensor-adapter").value !== "serial";
  $("sensor-address").hidden = $("sensor-adapter").value === "serial";
});
$("disconnect").addEventListener("click", () => action($("disconnect"), () => api("/api/disconnect", {})));
form.addEventListener("submit", event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form)); values.warmup_ack = form.elements.warmup_ack.checked;
  action($("start"), async () => { await api("/api/start", values); selectedScan = null; form.elements.sample_id.value = ""; });
});
const activeCommand = () => ({scan_id:state?.recorder.active?.id});
$("advance").addEventListener("click", () => action($("advance"), () => api("/api/phase", activeCommand())));
$("abort").addEventListener("click", () => action($("abort"), () => api("/api/abort", activeCommand())));
$("finish").addEventListener("click", () => action($("finish"), async () => {
  const result = await api("/api/finish", activeCommand()); await openScan(result.scan_id); tab("dataset");
}));
$("train").addEventListener("click", () => action($("train"), () => api("/api/train", {heldout_group:$("heldout").value,profile_key:$("training-profile").value || undefined})));
$("training-profile").addEventListener("change", () => { renderReadiness(); renderModel(); });
$("predict").addEventListener("click", () => action($("predict"), async () => {
  const result = await api("/api/predict", {scan_id:$("predict-scan").value}); renderPrediction($("prediction"), result);
}));
$("predict-detail").addEventListener("click", () => action($("predict-detail"), async () => {
  if (!selectedScan) throw new Error("Select a scan first.");
  const result = await api("/api/predict", {scan_id:selectedScan.id}); renderPrediction($("detail-prediction"), result);
}));
$("close-detail").addEventListener("click", () => { $("scan-detail").hidden = true; selectedScan = null; });
$("backup").addEventListener("click", event => {
  if (state?.recorder.active) { event.preventDefault(); showError("Finish or abort the current scan before making a full backup."); }
});
$("scans").addEventListener("click", event => {
  const button = event.target.closest("button[data-scan]");
  if (button) action(button, () => openScan(button.dataset.scan));
});

function chart(target, rows) {
  const data = rows.filter(r => Number.isFinite(r.gas_ohm) && Number.isFinite(r.elapsed_s));
  if (data.length < 2) { target.innerHTML = '<div class="chart-empty">Waiting for response measurements.</div>'; return; }
  const w=720, h=270, left=60, right=20, top=18, bottom=40;
  const minT = data[0].elapsed_s, maxT = Math.max(minT+.01, data.at(-1).elapsed_s);
  let minG=Infinity,maxG=-Infinity;
  for (const r of data) { minG=Math.min(minG,r.gas_ohm/1000); maxG=Math.max(maxG,r.gas_ohm/1000); }
  const padding=Math.max((maxG-minG)*.12,1); minG-=padding; maxG+=padding;
  const x=t=>left+(t-minT)/(maxT-minT)*(w-left-right), y=g=>top+(maxG-g)/(maxG-minG)*(h-top-bottom);
  const colors={baseline:"#edf2ec",exposure:"#e1ecda",recovery:"#f1f3e3"};
  const bands = ["baseline","exposure","recovery"].map(phase=> {
    const points=data.filter(r=>r.phase===phase); if (!points.length) return "";
    const start=x(points[0].elapsed_s), end=x(Math.min(maxT, points.at(-1).elapsed_s + 1));
    return `<rect x="${start.toFixed(2)}" y="${top}" width="${Math.max(0,end-start).toFixed(2)}" height="${h-top-bottom}" fill="${colors[phase]}"/>`;
  }).join("");
  let grid="";
  for(let i=0;i<5;i++){const gas=minG+(maxG-minG)*i/4, yy=y(gas);grid+=`<line x1="${left}" y1="${yy}" x2="${w-right}" y2="${yy}" stroke="#d9e2d6" stroke-width=".7"/><text x="${left-9}" y="${yy+4}" text-anchor="end" fill="#788575" font-size="10">${gas.toFixed(1)}</text>`;}
  for(let i=0;i<5;i++){const t=minT+(maxT-minT)*i/4;grid+=`<text x="${x(t)}" y="${h-17}" text-anchor="middle" fill="#788575" font-size="10">${t.toFixed(0)}s</text>`;}
  // Downsample display only. The database and extracted features retain every reading.
  const stride = Math.max(1, Math.ceil(data.length/800));
  const shown=data.filter((_,i)=>i%stride===0 || i===data.length-1);
  const line=shown.map(r=>`${x(r.elapsed_s).toFixed(2)},${y(r.gas_ohm/1000).toFixed(2)}`).join(" ");
  target.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Gas resistance in kiloohms versus elapsed seconds"><text x="${left}" y="12" fill="#788575" font-size="9">kΩ</text>${bands}${grid}<polyline points="${line}" fill="none" stroke="#315d41" stroke-width="2" stroke-linejoin="round"/></svg>`;
}

function renderRecorder(recorder) {
  const active=recorder.active, ours=active?.mode===mode;
  const latest=ours ? active.readings.at(-1) : (recorder.connected_mode===mode ? recorder.latest : null);
  $("gas-value").innerHTML = `${latest ? (latest.gas_ohm/1000).toFixed(1) : "—"}<small> kΩ</small>`;
  $("temp-value").innerHTML = `${Number.isFinite(latest?.temperature_c) ? latest.temperature_c.toFixed(1) : "—"}<small> °C</small>`;
  $("humidity-value").innerHTML = `${Number.isFinite(latest?.humidity_pct) ? latest.humidity_pct.toFixed(1) : "—"}<small> %</small>`;
  $("start").disabled=!!active || (mode==="real" && recorder.connected_mode!=="real");
  $("connect").disabled=!!active || recorder.connected_mode==="real";
  $("disconnect").disabled=!!active || recorder.connected_mode!=="real";
  $("connection-state").textContent=recorder.connected_mode==="real" ? `${recorder.sensor.device_id} · ${Math.floor(recorder.connected_seconds/60)} min connected` : "Disconnected";
  form.elements.device_id.readOnly = recorder.connected_mode === "real";
  if(recorder.connected_mode === "real") form.elements.device_id.value = recorder.sensor.device_id;
  $("live-badge").textContent=ours ? `${active.phase.toUpperCase()} · ${Math.floor(active.phase_elapsed_s)} s` : "READY";
  $("live-badge").classList.toggle("live",ours);
  $("abort").disabled=!ours; $("advance").disabled=!ours || active.phase==="recovery" || (active.counts[active.phase] || 0)<8;
  $("finish").disabled=!ours || active.phase!=="recovery" || (active.counts.recovery || 0)<8;
  if (ours) {
    chart($("live-chart"),active.readings);
    const help={baseline:["Baseline: clean air.","Let the response settle. Starting target: 30 seconds, then expose the sample."],exposure:["Exposure: present the sample.","Use the same chamber and sampling distance. Starting target: 60 seconds."],recovery:["Recovery: return to clean air.","Starting target: 90 seconds. Allow longer if resistance has not returned near baseline."]}[active.phase];
    $("phase-help").innerHTML=`<b>${help[0]}</b><span>${help[1]} ${active.counts[active.phase] || 0} readings captured.</span>`;
    $("advance").textContent=active.phase==="baseline" ? "Expose sample →" : "Return to clean air →";
  } else {
    $("phase-help").innerHTML='<b>Ready when you are.</b><span>Start with clean air, expose the sample, then return to clean air.</span>';
    $("advance").textContent="Expose sample →";
  }
  if(recorder.error) showError(recorder.error);
}

function updateSelect(select, entries, fallback) {
  const previous=select.value, signature=JSON.stringify(entries);
  if(select.dataset.signature===signature) return;
  select.dataset.signature=signature;
  select.innerHTML=entries.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join("");
  if(entries.some(([value])=>value===previous)) select.value=previous;
  else if(fallback && entries.some(([value])=>value===fallback)) select.value=fallback;
}

function renderDataset() {
  const scans=state.scans, completed=scans.filter(s=>s.status==="complete");
  $("nav-count").textContent=$("scan-count").textContent=scans.length;
  $("complete-count").textContent=completed.length;
  $("group-count").textContent=state.groups.length;
  $("label-count").textContent=new Set(completed.filter(s=>s.kind==="known").map(s=>s.label)).size;
  $("dataset-empty").hidden=scans.length>0;
  const signature=JSON.stringify(scans.map(s=>[s.id,s.status,s.sample_count]));
  if(signature!==datasetSignature){
    datasetSignature=signature;
    $("scans").innerHTML=scans.map(s=>`<tr><td>${esc(s.label)}<small>${esc(s.sample_id)} · ${esc(s.id.slice(0,8))}</small></td><td>${esc(s.group_id)}</td><td>${esc(s.kind)}</td><td>${s.sample_count}</td><td><span class="status ${s.status==="complete"?"complete":""}">${esc(s.status)}</span></td><td><button class="button quiet" data-scan="${esc(s.id)}">View ↗</button></td></tr>`).join("");
  }
}

function renderModel() {
  const model=state.model;
  const cohort=readiness?.cohorts.find(c=>c.profile_key===$("training-profile").value);
  const groups=cohort?.collection_days || state.groups;
  updateSelect($("heldout"),groups.map(g=>[g,g]),model?.heldout_group || groups.at(-1));
  const trainIds=new Set(model?.train_scan_ids || []);
  const modelCohort=readiness?.cohorts.find(c=>c.profile_key===model?.signal_profile_key);
  const compatibleIds=modelCohort ? new Set(modelCohort.scan_ids) : null;
  const eligible=state.scans.filter(s=>s.status==="complete" && !trainIds.has(s.id) && (!compatibleIds || compatibleIds.has(s.id)));
  updateSelect($("predict-scan"),eligible.map(s=>[s.id,`${s.label} · ${s.group_id} · ${s.id.slice(0,6)}`]));
  $("train").disabled=groups.length<3;
  $("predict").disabled=!model || !eligible.length;
  if(selectedScan) $("predict-detail").disabled=!model || selectedScan.status!=="complete" || trainIds.has(selectedScan.id);
  if(modelSignature===(model?.model_id || "none")) return;
  modelSignature=model?.model_id || "none";
  $("evaluation").hidden=!model;
  if(!model){$("model-summary").textContent="No model yet. Load the demo dataset or collect at least three days of real scans.";return;}
  const report=model.report;
  $("model-summary").textContent=`${report.train_count} training scans · ${report.test_count} test scans. Training days: ${model.train_groups.join(", ")}. Test day: ${model.heldout_group}.`;
  $("evaluation-note").textContent=report.evaluation_note;
  $("metric-identification").textContent=pct(report.known_identification_rate);
  $("metric-coverage").textContent=pct(report.known_coverage);
  $("metric-accuracy").textContent=pct(report.accepted_accuracy);
  $("metric-unknown").textContent=pct(report.unknown_rejection_rate);
  $("unknown-count").textContent=report.unknown_count ? `${report.unknown_count} unknown / blank controls` : "No unknown or blank controls";
  const labels=report.matrix_labels;
  $("matrix").innerHTML=`<table><thead><tr><th>Actual ↓ / Predicted →</th>${labels.map(l=>`<th>${esc(l)}</th>`).join("")}</tr></thead><tbody>${report.confusion_matrix.map((row,i)=>`<tr><td>${esc(labels[i])}</td>${row.map(n=>`<td>${n}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderPrediction(target,result) {
  target.innerHTML=`<div class="prediction"><p class="result-label">${result.decision==="match" ? esc(result.label) : "Unknown / no reliable match"}</p><p class="small">${result.mode==="simulation" ? "Synthetic software result · " : "Provisional result · "}candidate scores below</p>${result.top_candidates.map(c=>`<div class="candidate"><span>${esc(c.label)}</span><progress max="1" value="${c.score.toFixed(4)}"></progress><span>${pct(c.score)}</span></div>`).join("")}${result.reasons.length ? `<ul class="reasons">${result.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>` : ""}${result.warnings.length ? `<p class="small">${result.warnings.map(esc).join(" ")}</p>` : ""}<p class="small">${esc(result.score_note)}</p></div>`;
}

async function openScan(id) {
  const scan=await api(`/api/scan?mode=${mode}&id=${encodeURIComponent(id)}`); selectedScan=scan;
  $("scan-detail").hidden=false;
  $("detail-title").textContent=scan.label;
  $("detail-meta").textContent=`${scan.group_id} · ${scan.bottle_id || "No bottle ID"} · ${scan.sample_id} · ${scan.device_id} · ${scan.status} · ${scan.readings.length} readings`;
  chart($("detail-chart"),scan.readings);
  $("detail-qc").textContent=(scan.qc?.warnings || []).join(" ") || "No heuristic quality flags. Inspect the curve before relying on it.";
  $("detail-prediction").replaceChildren();
  $("predict-detail").disabled=!state?.model || scan.status!=="complete" || state.model.train_scan_ids.includes(scan.id);
}

async function refresh(force=false) {
  if(refreshing) return;
  refreshing=true;
  const requestedMode=mode;
  try {
    const next=await api(`/api/state?mode=${requestedMode}`);
    if(mode!==requestedMode) return;
    state=next; renderRecorder(state.recorder); renderDataset(); renderModel();
    if (!catalogue || catalogueSignature !== JSON.stringify(state.catalogue_summary)) await loadCatalogue();
    if(mode!==requestedMode) return;
    const completeSignature=JSON.stringify([mode,state.scans.filter(s=>s.status==="complete").map(s=>s.id)]);
    if (!readiness || readinessSignature!==completeSignature) {
      const pendingReadiness=await api(`/api/readiness?mode=${requestedMode}`);
      if(mode!==requestedMode) return;
      readiness=pendingReadiness;
      readinessSignature=completeSignature;
      updateSelect($("training-profile"),readiness.cohorts.map(c=>[c.profile_key,`${c.definition.adapter_id} · ${c.definition.profile} · ${c.profile_key.slice(0,8)}`]),state.model?.signal_profile_key);
      renderReadiness(); renderModel();
    }
    if(state.index_errors?.length) showError("Raw scans are preserved, but some reference indexes need attention. Back up your data and inspect the affected scan: "+state.index_errors.map(e=>e.scan_id.slice(0,8)+": "+e.error).join("; "));
    if(historySignature!==mode+":"+(state.model?.model_id||"none")) {
      const history=await api(`/api/model-runs?mode=${requestedMode}`);
      if(mode!==requestedMode) return;
      historySignature=mode+":"+(state.model?.model_id||"none");
      $("model-history").innerHTML=history.runs.length ? history.runs.map(r=>`<p><b>${esc(r.model_id.slice(0,8))}</b> · ${esc(r.heldout_group)} · ${r.report?.train_count || 0} training scans · identification ${pct(r.report?.known_identification_rate)} · <a href="/api/v1/model-run?mode=${mode}&amp;id=${encodeURIComponent(r.model_id)}" target="_blank" rel="noopener">Model and report JSON ↗</a></p>`).join("") : "No training runs yet.";
    }
    if(force && !state.recorder.active) $("live-chart").innerHTML='<div class="chart-empty">Start a scan to see the sensor response.</div>';
  } catch(error){showError(`Cannot reach Olfy. Check that it is running in Terminal. ${error.message}`);}
  finally{refreshing=false;}
}
initializeNavigation();
setInterval(refresh,1000);

function renderReadiness() {
  const cohort=readiness?.cohorts.find(c=>c.profile_key===$("training-profile").value);
  if (!cohort) {
    $("readiness-summary").textContent=mode==="real" ? "No complete real references yet. Choose 2–5 authentic perfumes in Reference 50, then collect baseline/exposure/recovery scans on three separate days." : "Load the demo dataset to exercise training with generated signals.";
    $("readiness-labels").replaceChildren(); return;
  }
  $("readiness-summary").textContent=`${cohort.labels.length} known labels · ${cohort.scan_count} complete scans · ${cohort.collection_days.length} collection days · ${cohort.control_count} unknown/blank controls. ${cohort.candidate_test_days.length ? "Candidate held-out days: "+cohort.candidate_test_days.join(", ")+"." : "No day meets all minimum collection counts yet."}`;
  $("readiness-labels").innerHTML=cohort.label_progress.map(l=>`<p class="small"><b>${esc(l.label)}</b> · ${l.scans} independent scans · ${l.days} collection days</p>`).join("");
}

function useSelectedReference() {
  const id = form.elements.fragrance_id.value;
  const item = catalogue?.fragrances.find(f => f.fragrance_id === id);
  form.elements.label.readOnly = !!item;
  if (item) {
    form.elements.label.value = item.label;
    form.elements.kind.value = "known";
  }
}
$("reference-perfume").addEventListener("change", useSelectedReference);
$("planned-sample").addEventListener("change", () => {
  if (state?.recorder.active) return showError("Finish or abort the current scan before selecting another sample.");
  const row = plannedRows[Number($("planned-sample").value)];
  if (!row || $("planned-sample").value === "") return;
  const now = new Date();
  const actualDay = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
  for (const key of ["fragrance_id", "label", "kind", "substrate", "dose", "drydown_min"]) form.elements[key].value = row[key];
  useSelectedReference();
  form.elements.group_id.value = actualDay;
  form.elements.sample_id.value = row.sample_id.replace(row.group_id, actualDay) + "-" + crypto.randomUUID().slice(0,6);
  form.elements.bottle_id.value = row.kind === "blank" ? "clean-air" : "";
  $("plan-hint").textContent = `Prepared for today's actual collection date (${actualDay}); planned date was ${row.group_id}. Use a fresh sample, enter the actual bottle ID, and verify dose, drydown and warm-up. No measurement has been made yet.`;
});
form.elements.kind.addEventListener("change", () => {
  if (form.elements.kind.value !== "known") {
    form.elements.fragrance_id.value = "";
    form.elements.label.readOnly = false;
  }
});
$("catalogue-rows").addEventListener("click", event => {
  const record = event.target.closest("button[data-reference-record]");
  const inspect = event.target.closest("button[data-reference-view]");
  if (record) action(record, async () => {
    if (state?.recorder.active) throw new Error("Finish or abort the current scan before selecting another perfume.");
    await setMode("real");
    form.elements.fragrance_id.value = record.dataset.referenceRecord;
    useSelectedReference();
    tab("record");
  });
  if (inspect) action(inspect, () => openReference(inspect.dataset.referenceView));
});
$("close-reference").addEventListener("click", () => { $("reference-detail").hidden = true; });

async function loadCatalogue() {
  catalogue = await api("/api/catalogue");
  const s = catalogue.summary;
  catalogueSignature = JSON.stringify(s);
  $("catalogue-count").textContent = s.perfume_count;
  $("catalogue-measured").textContent = s.measured_count;
  $("catalogue-pending").textContent = s.pending_count;
  $("catalogue-references").textContent = s.reference_count;
  $("catalogue-scope").textContent = catalogue.selection_scope;
  $("catalogue-sensor-fields").textContent = "Raw channels: gas resistance (ohm), temperature (°C), humidity (%RH), pressure (hPa), heater temperature (°C) and heater duration (ms). Declared extra sensor channels are preserved. Fingerprints use 12 features from the baseline-normalized resistance curve; environment readings remain attached for inspection.";
  updateSelect($("reference-perfume"), [["", "Custom sample / control"], ...catalogue.fragrances.map(f => [f.fragrance_id, f.label])]);
  $("catalogue-rows").innerHTML = catalogue.fragrances.map(f => `<tr><td>${f.selection_order}</td><td>${esc(f.brand)}<small>${esc(f.name)} · <a href="${esc(f.product_url)}" target="_blank" rel="noopener noreferrer">Retailer source ↗</a></small></td><td>${esc(f.concentration_label || "Check exact bottle")}</td><td>${f.usable_count} usable / ${f.reference_count} total</td><td><span class="status ${f.measurement_status === "measured" ? "complete" : ""}">${esc(f.measurement_status.replaceAll("_", " "))}</span></td><td><button class="button quiet" data-reference-view="${esc(f.fragrance_id)}">View</button><button class="button secondary" data-reference-record="${esc(f.fragrance_id)}">Record →</button></td></tr>`).join("");
}

async function openReference(id) {
  const result = await api(`/api/catalogue?id=${encodeURIComponent(id)}`);
  const f = result.fragrances[0];
  $("reference-title").textContent = f.label;
  $("reference-detail").hidden = false;
  $("reference-body").innerHTML = `<p>${esc(f.fragrance_id)} · ${esc(f.concentration_label || "Concentration label not specified in this listing; verify the bottle.")}</p><p>${esc(result.measurement_note)}</p>` + (result.measurements.length ? result.measurements.map(m => `<div class="reference-measurement"><p><b>${esc(m.device_id)}</b> · ${esc(m.sensor.profile)} · ${esc(m.conditions.group_id)} · ${esc(m.status)} · ${m.sample_count} sensor samples</p><p>Bottle ${esc(m.conditions.bottle_id)} · ${esc(m.conditions.substrate)} · drydown ${esc(m.conditions.drydown_min)} min · ${esc(m.conditions.dose)}</p>${m.features ? `<p>${Object.entries(m.features).map(([name, value]) => `${esc(name)}: ${Number(value).toFixed(4)}`).join(" · ")}</p>` : ""}<p>${(m.quality.warnings || []).map(esc).join(" ")}</p><button class="button quiet" data-raw-reference="${esc(m.scan_id)}">Inspect raw scan ↗</button><a class="button quiet" href="${esc(m.samples_url)}" target="_blank" rel="noopener">Sensor samples JSON ↗</a></div>`).join("") : "<p><b>Awaiting real sensor measurements.</b> Record several independent samples across different collection days before training. Start with 2–5 perfumes to test whether the hardware separates them.</p>");
}
$("reference-body").addEventListener("click", event => {
  const button = event.target.closest("button[data-raw-reference]");
  if (button) action(button, async () => { await setMode("real"); await openScan(button.dataset.rawReference); tab("dataset"); });
});

async function initializeNavigation() {
  await refresh(true);
  const query = new URLSearchParams(location.search);
  const wantedMode = state?.recorder.active?.mode || (query.get("mode") === "real" ? "real" : "simulation");
  if (wantedMode !== mode) await setMode(wantedMode, {recover:true});
  const wantedTab = query.get("tab");
  if (["record", "dataset", "catalogue", "model"].includes(wantedTab)) tab(wantedTab);
  try {
    const result = await api("/api/plan");
    plannedRows = result.rows;
    updateSelect($("planned-sample"), [["", "Choose a planned fresh sample"], ...plannedRows.map((r,i) => [String(i), `${r.group_id} · ${r.label} · ${r.sample_id.split("-").slice(-1)[0]}`])]);
    $("planned-sample-field").hidden = mode !== "real" || !plannedRows.length;
  } catch (error) { showError("Could not load the experiment plan. " + error.message); }
}
