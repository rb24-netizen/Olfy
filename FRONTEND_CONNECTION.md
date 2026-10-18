# Connecting your existing Olfy frontend

**Figma consumer interface is now integrated:** the React export is in `frontend/`, its compiled assets are in `olfy/web/consumer/`, and the default homepage uses the shared sensor SDK. Its service implementation connects the consumer controls to the same recorder and databases as Lab. This file's remaining port-8000 instructions apply to the separate earlier green dashboard.

Your screenshot shows a local Olfy dashboard at `http://127.0.0.1:8000`, with Overview, Fragrance library, Scan laboratory and Hardware screens. This is a separate project from the research UI in this archive.

`Olfy_Starter.zip` is the source of the sensor/recognition prototype. It contains a working research frontend, Python backend, scan database, classifier and interchangeable sensor adapters. Running `bash start.sh` opens that project's frontend at `http://127.0.0.1:8765`. Opening an HTML file directly does not run its backend.

The screenshot frontend has not yet been edited or connected because its project source has not been supplied. Keep its design and catalog. The included browser connector gives that project a direct route to the sensor backend once its handlers are updated.

## Start both applications

Keep the existing frontend running on port 8000. From this unzipped project folder, start the sensing backend with both local frontend origins explicitly allowed:

```bash
bash start.sh --allow-origin http://127.0.0.1:8000 \
  --allow-origin http://localhost:8000
```

Add `--hardware` when you have the BME688/MCP2221 setup and want to install its optional drivers. This backend uses port 8765; it does not replace the existing app on port 8000.

## Connect frontend handlers

The portable ES module is `olfy/web/olfy-client.js`. Your frontend can import it from the backend (with the allowed origin above), or copy the module into its own assets:

```javascript
import {OlfyClient} from "http://127.0.0.1:8765/olfy-client.js";

const sensing = new OlfyClient({mode:"real"});
const device = await sensing.connectSensor("bme688", {address:"auto"});
const live = await sensing.status();
console.log(device.sensor, live.latest);
```

Integrate the returned values with the existing UI state:

| Existing screen | Backend connection |
| --- | --- |
| Hardware | `adapters()`, `connectSensor()`, `status()`, `disconnect()` |
| Scan laboratory | `startScan()`, `nextPhase()`, `finishScan()`, `abortScan()`, `getScan()` |
| Overview counters | Actual scan counts and reading counts from `state().scans` |
| Recognition result | `predict(scanId)` after a compatible measured model is trained |
| Fragrance library | Keep the catalog; use its selected fragrance's full label when collecting known training samples |

For a labeled collection session, pass the selected catalog fragrance and the actual sampling metadata to `startScan`. Save the returned `scan_id` in your frontend's session record so the two applications can refer to the same measurement. Do not present fragrance catalog entries as measured fingerprints.

```javascript
const {scan_id} = await sensing.startScan({
  label: selectedFragranceLabel,
  group_id: collectionDay,
  bottle_id: bottleId,
  substrate: "paper blotter",
  dose: doseDescription,
  drydown_min: drydownMinutes,
  warmup_ack: warmupConfirmed
});
```

Poll `status()` about once per second for live values and phase counts. Connect your existing controls to phase changes after the proper physical sample handling and timings. At least eight readings are required per phase. `finishScan()` stores a completed baseline/exposure/recovery scan. Predictions use the same recorded `scan_id`.

For development without hardware, instantiate the client with `mode:"simulation"`, then call `loadDemo()` and `train("demo-day-4")`. Keep the artificial-data label visible anywhere demo data or results appear. Real connection errors never trigger a switch to simulated readings.

The client manages the local write token, exposes errors with `code` and `status`, and rejects uncertain network failures without automatically duplicating scan commands. See `INTEGRATION.md` and `openapi.json` for the full interface.

## Source needed for the final wiring

Provide the existing port-8000 application's project folder as a ZIP, including its frontend templates/components, JavaScript, backend routes and dependency files. Exclude virtual environments, `node_modules` and credentials. Those source files are needed to attach the connector to the actual controls, preserve its catalog/session schema and verify the complete interface.
