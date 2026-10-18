/** Portable browser client for connecting an existing UI to Olfy's sensor API. */
export class OlfyError extends Error {
  constructor(message, code, status) {
    super(message);
    this.name = "OlfyError";
    this.code = code;
    this.status = status;
  }
}

export class OlfyClient {
  constructor({baseUrl = "http://127.0.0.1:8765", mode = "real", timeoutMs = 15000} = {}) {
    if (!["real", "simulation"].includes(mode)) throw new Error("Choose real or simulation mode.");
    this.baseUrl = baseUrl.replace(/\/$/, "") + "/api/v1";
    this.mode = mode;
    this.timeoutMs = timeoutMs;
    this.token = null;
  }

  async request(endpoint, {data, query, retryToken = true} = {}) {
    if (data !== undefined && !this.token) this.token = (await this.state()).csrf_token;
    const url = new URL(`${this.baseUrl}/${endpoint}`);
    if (query) for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response, result;
    try {
      response = await fetch(url, {
        method: data === undefined ? "GET" : "POST",
        headers: data === undefined ? {Accept:"application/json"} : {
          "Content-Type":"application/json", "X-Olfy-Token":this.token
        },
        body: data === undefined ? undefined : JSON.stringify(data),
        signal: controller.signal
      });
      result = await response.json();
    } catch (error) {
      throw new OlfyError(error.name === "AbortError"
        ? "Olfy timed out. Check status before repeating a scan command."
        : "Cannot reach Olfy. Start the backend and allow this frontend's origin.",
        "connection_error", 0);
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) {
      // A rejected token means no command ran. Do not retry uncertain failures.
      if (response.status === 403 && result.code === "invalid_token" && retryToken) {
        this.token = (await this.state()).csrf_token;
        return this.request(endpoint, {data, query, retryToken:false});
      }
      throw new OlfyError(result.error || "Olfy request failed.", result.code, response.status);
    }
    return result;
  }

  state() { return this.request("state", {query:{mode:this.mode}}); }
  status() { return this.request("status"); }
  setup() { return this.request("setup"); }
  practice() { return this.request("practice", {data:{mode:"simulation"}}); }
  experimentPlan() { return this.request("plan"); }
  saveExperimentPlan(plan) { return this.request("plan", {data:{...plan,mode:"real"}}); }
  planCsvUrl() { return `${this.baseUrl}/plan/export`; }
  adapters() { return this.request("adapters"); }
  catalogue(fragranceId) { return this.request("catalogue", {query:fragranceId ? {id:fragranceId} : undefined}); }
  catalogueUrl() { return `${this.baseUrl}/catalogue/export`; }
  readiness() { return this.request("readiness", {query:{mode:this.mode}}); }
  saveScan(scanId,saved=true) { return this.request("bookmark", {data:{mode:this.mode,scan_id:scanId,saved}}); }
  backupUrl() { return `${this.baseUrl}/backup`; }
  connectSensor(adapterId = "bme688", config = {}) {
    return this.request("connect", {data:{mode:"real", adapter_id:adapterId, config}});
  }
  disconnect() { return this.request("disconnect", {data:{}}); }
  startScan(metadata) { return this.request("start", {data:{...metadata, mode:this.mode}}); }
  startCapture(metadata, durationSeconds=10) { return this.request("capture", {data:{...metadata, mode:this.mode, duration_s:durationSeconds}}); }
  nextPhase(scanId) { return this.request("phase", {data:{mode:this.mode, scan_id:scanId}}); }
  finishScan(scanId) { return this.request("finish", {data:{mode:this.mode, scan_id:scanId}}); }
  abortScan(scanId) { return this.request("abort", {data:{mode:this.mode, scan_id:scanId}}); }
  getScan(scanId) { return this.request("scan", {query:{mode:this.mode, id:scanId}}); }
  train(heldoutGroup,profileKey) { return this.request("train", {data:{mode:this.mode, heldout_group:heldoutGroup,profile_key:profileKey}}); }
  predict(scanId) { return this.request("predict", {data:{mode:this.mode, scan_id:scanId}}); }
  loadDemo() { return this.request("seed", {data:{mode:"simulation"}}); }
  csvUrl() { return `${this.baseUrl}/export?mode=${encodeURIComponent(this.mode)}`; }
}
