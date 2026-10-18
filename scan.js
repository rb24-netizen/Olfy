import {OlfyClient} from "./olfy-client.js";

const $ = id => document.getElementById(id);
const client = new OlfyClient({baseUrl:window.location.origin, mode:"simulation"});
const phases = {
  baseline:{seconds:30, title:"Finding the baseline", hint:"Keep the sensor in clean air.", next:"Present the sample"},
  exposure:{seconds:60, title:"Reading the scent", hint:"Keep the sample at a fixed distance.", next:"Remove the sample"},
  recovery:{seconds:90, title:"Letting the sensor recover", hint:"Keep the sensor in clean air.", next:"Finish the scan"}
};
let state = null, recorder = null, busy = false, online = false, pollTimer = null, demoIndex = 0, refreshSequence = 0;

function tell(text, target="message") {
  $(target).textContent = text || "";
  $(target).hidden = !text;
}
function openSheet(id) { if (!$(id).open) $(id).showModal(); }
function setBusy(value) { busy=value; render(); }
function render() {
  const real = client.mode === "real", active = recorder?.active;
  const connected = recorder?.connected_mode === "real";
  $("demo-mode").classList.toggle("selected", !real);
  $("real-mode").classList.toggle("selected", real);
  $("demo-mode").disabled = $("real-mode").disabled = busy || !!active;
  $("real-settings").hidden = !real;
  $("settings-copy").textContent = real ? "Connect your prototype sensor. Real measurements stay separate from demo data." : "Demo uses artificial reference scans to test the app. It does not identify a real fragrance.";
  $("subtitle").textContent = real ? "Hold your sensor near a scent. Tap to capture." : "Tap the circle to explore a demo.";
  $("connection-label").textContent = real ? (connected ? "Sensor connected" : "Connect your sensor") : "Demo mode";
  $("status-dot").classList.toggle("connected", real && connected);
  $("mode-note").textContent = real ? "10-second capture. Identification needs measured references." : "Generated signals. No perfume measured.";
  $("connect-button").disabled = busy || !!active;
  $("disconnect-button").disabled = busy || !!active || !connected;
  $("adapter-select").disabled = busy || !!active;
  $("serial-port").disabled = busy || !!active;
  $("warmup-check").disabled = busy || !!active;
  $("device-detail").textContent = connected ? `${recorder.sensor.adapter_id} · ${recorder.sensor.device_id} · Connected ${recorder.connected_seconds}s` : "No sensor connected.";
  $("abort-button").hidden = !active;
  $("abort-button").disabled = busy || !online;
  $("orb-stage").classList.toggle("is-working", busy || !!active);
  let enabled = online && !busy;
  let label = "Tap to discover", hint = real ? "Hold the sample steady for 10 seconds." : "One circle. A new discovery.";
  if (active?.capture_mode === "quick") {
    const remaining=Math.max(0,Math.ceil(active.target_seconds-active.phase_elapsed_s));
    label=`Sensing · ${remaining}s`;
    hint="Hold steady. Your capture will finish automatically.";
    enabled=false;
  } else if (active) {
    const p = phases[active.phase], remaining = Math.max(0, Math.ceil(p.seconds-active.phase_elapsed_s));
    label = remaining ? `${p.title} · ${remaining}s` : p.next;
    hint = remaining ? p.hint : `${p.hint} Tap the circle when ready.`;
    enabled = enabled && active.mode===client.mode && remaining===0 && (active.counts[active.phase] || 0)>=8;
  } else if (busy) { label = real ? "Working with your sensor" : "Reading the demo"; hint = real ? "Checking the current scan status." : "Comparing a generated reference signal."; }
  else if (real && !connected) { label = "Connect to begin"; hint = "Your sensor is one tap away."; }
  else if (real) { label = "Tap to scan"; }
  if (!online && !busy) { label = "Olfy is offline"; hint = "Start Olfy in Terminal, then reload this page."; }
  $("scan-label").textContent = label;
  $("scan-hint").textContent = hint;
  $("scan-button").disabled = !enabled;
  $("scan-button").setAttribute("aria-label", label);
}
async function refresh() {
  const sequence = ++refreshSequence;
  const requestedMode = client.mode;
  const next = await client.state();
  if (requestedMode !== client.mode || sequence !== refreshSequence) return;
  const previousQuick=recorder?.active?.capture_mode==="quick" ? recorder.active.id : null;
  state = next; recorder = state.recorder; online = true;
  // A scan begun in Lab remains controllable here, using its original workspace.
  if (recorder.active && recorder.active.mode !== client.mode) {
    client.mode = recorder.active.mode;
    return refresh();
  }
  if (recorder.error) tell(recorder.error);
  render();
  if(previousQuick && !recorder.active && state.scans.some(s=>s.id===previousQuick && s.status==="captured")) await showCapture(previousQuick);
}
async function poll() {
  try { if (!busy) await refresh(); }
  catch (error) { online=false; tell(error.message); render(); }
  finally { pollTimer=setTimeout(poll, 1500); }
}
async function act(task, errorTarget="message") {
  if (busy) return;
  setBusy(true); tell("", errorTarget);
  try { await task(); await refresh(); }
  catch (error) {
    tell(error.message, errorTarget);
    // Scan mutations are never repeated automatically after an uncertain result.
    try { await refresh(); } catch { online=false; }
  }
  finally { setBusy(false); }
}
function showResult(title, copy, note, demo=false) {
  $("result-eyebrow").textContent = demo ? "DEMO RESULT" : "PROTOTYPE RESULT";
  $("result-title").textContent=title;
  $("result-copy").textContent=copy;
  $("result-note").textContent=note;
  openSheet("result-dialog");
}
async function showCapture(id) {
  const scan=await client.getScan(id), seconds=scan.readings.at(-1)?.elapsed_s || scan.capture_duration_s;
  showResult("Signal captured",`${scan.readings.length} sensor readings saved over ${Math.round(seconds)} seconds. You can inspect and export them in Lab.`,"No perfume has been identified from this short capture. A model validated for this capture protocol is needed.");
  $("result-eyebrow").textContent="REAL SENSOR CAPTURE";
}
async function identify(id) {
  if(state?.scans.some(s=>s.id===id && s.status==="captured")){await showCapture(id);return;}
  if (!state?.model) {
    showResult("Scan saved", "Your sensor recording is saved. Collect labelled reference samples and train a model in Lab to compare scents.", "No perfume identification was made.");
    return;
  }
  const result = await client.predict(id), demo=client.mode==="simulation";
  showResult(result.decision==="match" ? result.label : "No reliable match",
    demo ? (result.decision==="match" ? "The generated signal matched an artificial reference label." : "This generated signal was rejected by the prototype model.") : (result.decision==="match" ? "Your recording matched this reference label in the prototype model." : (result.reasons.join(" ") || "The sample needs a clearer signal or more reference data.")),
    demo ? "Software demonstration only. No real perfume was scanned. These labels are not perfume brands." : "The model and rejection thresholds need validation with real perfumes. This result is provisional.", demo);
}
async function demoScan() {
  await client.loadDemo();
  await refresh();
  if (!state.model) { await client.train("demo-day-4"); await refresh(); }
  const trained = new Set(state.model.train_scan_ids);
  const examples = state.scans.filter(s=>s.status==="complete" && !trained.has(s.id) && s.kind==="known" && s.group_id==="demo-day-4").sort((a,b)=>a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
  if (!examples.length) throw new Error("No unseen demo example is available. Choose a held-out day in Lab.");
  await identify(examples[demoIndex++ % examples.length].id);
}
async function scan() {
  if (!recorder?.active && client.mode==="real" && (recorder?.connected_mode!=="real" || !$("warmup-check").checked)) {
    openSheet("settings-dialog");
    tell("Connect the sensor and confirm its clean-air warm-up before starting.", "settings-message");
    return;
  }
  await act(async()=>{
    const active = recorder?.active;
    if (active) {
      if (active.phase==="recovery") {
        const result = await client.finishScan(active.id);
        await refresh();
        await identify(result.scan_id);
      } else { await client.nextPhase(active.id); }
    } else if (client.mode==="simulation") { await demoScan(); }
    else {
      await client.startCapture({label:"Unlabelled capture",kind:"unknown",group_id:`consumer-${new Date().toISOString().slice(0,10)}`,bottle_id:"unlabelled-sample",substrate:"not recorded",dose:"not recorded",drydown_min:0,warmup_ack:$("warmup-check").checked,notes:"Consumer quick capture. Exact substrate, dose and drydown were not recorded; this raw clip is excluded from the three-phase reference classifier."},10);
    }
  });
}
async function switchMode(mode) {
  if (busy || recorder?.active || mode===client.mode) return;
  await act(async()=>{client.mode=mode; await refresh();}, "settings-message");
}
$("scan-button").addEventListener("click", scan);
for (const id of ["settings-button","connection-button"]) $(id).addEventListener("click",()=>openSheet("settings-dialog"));
for (const button of document.querySelectorAll(".close-dialog")) button.addEventListener("click",()=>button.closest("dialog").close());
$("result-done").addEventListener("click",()=>$("result-dialog").close());
$("demo-mode").addEventListener("click",()=>switchMode("simulation"));
$("real-mode").addEventListener("click",()=>switchMode("real"));
$("adapter-select").addEventListener("change",()=>{for (const el of document.querySelectorAll(".serial-field")) el.hidden=$("adapter-select").value!=="serial";});
$("connect-button").addEventListener("click",()=>act(async()=>{
  const adapter=$("adapter-select").value;
  await client.connectSensor(adapter, adapter==="bme688" ? {address:"auto"} : {port:$("serial-port").value.trim() || "auto",baud_rate:115200});
  $("warmup-check").checked=false;
},"settings-message"));
$("disconnect-button").addEventListener("click",()=>act(async()=>{await client.disconnect();$("warmup-check").checked=false;},"settings-message"));
$("abort-button").addEventListener("click",()=>act(async()=>{if(recorder?.active) await client.abortScan(recorder.active.id);}));
$("saved-button").addEventListener("click",async()=>{
  await act(async()=>{
    await refresh();
    $("saved-eyebrow").textContent=client.mode==="simulation" ? "DEMO WORKSPACE" : "REAL WORKSPACE";
    const list=$("saved-list"); list.replaceChildren();
    const complete=state.scans.filter(s=>["complete","captured"].includes(s.status)).slice(0,20);
    if(!complete.length){const p=document.createElement("p");p.className="empty-state";p.textContent="Your first discovery starts with the circle. Completed scans will appear here.";list.append(p);}
    for(const s of complete){
      const row=document.createElement("button");row.className="saved-row";
      const details=document.createElement("div"),label=document.createElement("span"),meta=document.createElement("small"),action=document.createElement("b");
      label.textContent=s.label;meta.textContent=`${s.group_id} · ${s.sample_count} readings`;details.append(label,meta);
      const training=state.model?.train_scan_ids.includes(s.id);
      action.textContent=training ? "Reference" : "View";row.append(details,action);row.disabled=!!training;
      row.addEventListener("click",()=>act(async()=>{$("saved-dialog").close();await identify(s.id);}));
      list.append(row);
    }
    openSheet("saved-dialog");
  });
});
window.addEventListener("pagehide",()=>clearTimeout(pollTimer));
poll();
