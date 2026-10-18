# Sensor connection and app integration

Olfy 0.2 separates **transport**, **measurement format**, **recording**, **classification** and **UI**. A sensor adapter supplies fresh measurements in declared units; the recorder stores them using the same scan format; another application controls that recorder through the versioned local API.

The built-in connections are:

| Adapter | Connection | Required setup |
| --- | --- | --- |
| `bme688` | BME688 → QT cable → MCP2221 → USB → Mac | `bash start.sh --hardware`; automatic I2C address detection by default |
| `serial` | Microcontroller → USB serial → Mac | `bash start.sh --serial`; firmware must emit the Olfy JSON protocol below |
| `simulation` | Artificial curves | No hardware dependencies; confined to simulation mode |

Hardware-specific drivers are optional and imported only when needed. Installing or running the simulator does not require a connected device. Physical USB connections still need validation on the Mac; the delivered automated connection tests use stub transports.

## Connect the recommended BME688

```bash
# Install optional drivers and open the workbench:
bash start.sh --hardware
```

Choose **Real sensor**, keep **BME688 / MCP2221** and **Auto address** selected, and click **Connect sensor**. The connection checks for one MCP2221 bridge, scans for a BME688 at `0x76` or `0x77`, configures the heater, and validates an initial reading. If multiple bridges or two sensor addresses are present, it asks you to select/unplug the ambiguous hardware rather than claiming a match.

Connected status reports the detected device ID. The recorder attaches that ID, the actual adapter's profile, channel units and transport metadata to each new scan. If you provide an assigned BME688 ID before connecting, keep it stable for that physical sensor. A USB bridge identity is not the BME688 chip's unique serial number; assign a new sensor ID when replacing a breakout on the same bridge.

To diagnose a connection without opening the dashboard:

```bash
bash start.sh --hardware --list-sensors
bash start.sh --hardware --check-sensor
# Optional explicit address and stable assigned ID:
bash start.sh --hardware --check-sensor --address 0x77 --device-id bme688-01
```

The diagnostic reads one sample and closes the connection. Passing it establishes a working link and valid numerical reading, not conditioning, scent selectivity or recognition accuracy. Warm up and inspect the baseline before experiments.

## USB serial protocol for a custom board

The serial adapter needs a local serial port, such as `/dev/cu.usbmodem1234`, and a matching baud rate (default `115200`). Port discovery lists USB serial devices; automatic port choice requires exactly one USB serial device. Opening some microcontroller serial ports can reset the board. Allow firmware to boot and begin streaming.

Send **one UTF-8 JSON object per line**, terminated by `\n`, ideally around once per second. This is an illustrative packet, not a real measurement:

```json
{
  "type": "olfy.sample",
  "schema_version": 1,
  "mode": "real",
  "device_id": "olfy-board-001",
  "profile": "bme688-forced-320C-150ms-v1",
  "source_sequence": 42,
  "gas_ohm": 102500,
  "temperature_c": 23.4,
  "humidity_pct": 41.2,
  "pressure_hpa": 1013.2,
  "heater_c": 320,
  "heater_ms": 150
}
```

Required fields: `type`, `schema_version`, `device_id`, `profile`, `source_sequence`, `gas_ohm`. `mode` defaults to real; a packet explicitly tagged simulation is rejected by the real adapter. All values must actually come from your sensor if recording real data.

`source_sequence` is a nonnegative integer that strictly increases. Reconnect after a board reset. Device identity and profile must stay stable for the connection. Change the profile identifier when changing sensor configuration or the measurement protocol, and collect/train a compatible dataset.

Canonical units are fixed by schema version 1:

| Field | Unit |
| --- | --- |
| `gas_ohm` | ohms; finite and strictly positive |
| `temperature_c`, `heater_c` | degrees Celsius |
| `humidity_pct` | percent relative humidity |
| `pressure_hpa` | hectopascals |
| `heater_ms` | milliseconds |

Environmental/heater fields are optional. Missing values show as unavailable in the UI. An optional `units` object can declare extra numeric channels, which go in `extra_channels`. For example:

```json
{
  "units": {"second_gas_ohm": "ohm"},
  "extra_channels": {"second_gas_ohm": 91000}
}
```

Merge those fields into the sample packet, not a separate line. Extra channels are preserved in the database and CSV. **The first classifier still uses `gas_ohm` only.** Using an array, optical spectrum or concentration sensor requires appropriate feature extraction and new training data; merely connecting its transport does not make the existing classifier suitable.

Packets are limited to 16 KiB. Malformed JSON, invalid values, changed units, duplicate/backwards sequences and timeouts stop a recording and preserve its partial data with error status. Queued older complete samples may be discarded to keep the recorder near the latest response; `source_sequence` exposes those gaps. A higher-rate research application needs its own acquisition-rate and buffering design.

```bash
bash start.sh --serial --check-sensor --adapter serial \
  --serial-port /dev/cu.usbmodem1234 --baud-rate 115200
```

The serial bridge receives data; it does not implement your board's firmware, drive a pump or change a remote heater setting. Firmware should implement the declared measurement profile. Bluetooth is a future transport adapter, not an implemented connection in this release.

## Python integration

The project is an installable Python package. In another application's environment, install the source folder once:

```bash
python -m pip install -e /absolute/path/to/olfy_starter
# Include optional hardware drivers when that application hosts the sensor:
python -m pip install -e '/absolute/path/to/olfy_starter[hardware]'
```

This also installs the `olfy` command. It records into `data/` in the current working directory by default; use `olfy --data-dir /path/to/my-recordings` to choose an explicit location. If you need only the HTTP client, `olfy/client.py` itself uses the standard library and can be incorporated into your app without the model or hardware dependencies.

Start the workbench first. From another Python module, use the included dependency-free client:

```python
from olfy.client import OlfyClient

olfy = OlfyClient("http://127.0.0.1:8765")
print(olfy.adapters())
connection = olfy.connect_sensor("bme688", address="auto")
print(connection["sensor"])
print(olfy.status()["latest"])

# After conditioning/warm-up and preparing a real sample:
scan_id = olfy.start_scan({
    "label": "Tom Ford Oud Wood EDP",
    "group_id": "2026-10-13",
    "bottle_id": "oud-wood-bottle-01",
    "substrate": "paper blotter",
    "dose": "1 spray; fixed chamber",
    "drydown_min": 5,
    "warmup_ack": True
})["scan_id"]
```

After the appropriate physical sample handling and phase timing:

```python
olfy.next_phase(scan_id)       # baseline → exposure
olfy.next_phase(scan_id)       # exposure → recovery
olfy.finish_scan(scan_id)      # preserve completed scan
scan = olfy.get_scan(scan_id)

# Once there is a suitable measured dataset and trained real model:
result = olfy.predict(scan_id)
```

Do not run the three phase commands immediately; each requires at least eight readings and the protocol needs consistent timings. Use `olfy.status()` to check the current phase and reading counts. To preserve and abort an unfinished scan: `olfy.finish_scan(scan_id, abort=True)`.

For USB serial: `olfy.connect_sensor("serial", port="/dev/cu.usbmodem1234", baud_rate=115200)`. Device identity comes from the firmware. For simulation experiments, use `olfy.load_demo()` and pass `mode="simulation"` to scan/train/predict methods.

The client obtains the local write token and refreshes it once after a rejected stale token. It does not retry uncertain network failures that could duplicate a recording. API errors raise `OlfyError` with `code` and HTTP `status`.

## Browser or other-language integration

The stable API prefix is `/api/v1/`. The earlier `/api/` paths remain compatibility aliases. JSON responses retain their named fields rather than a new wrapper.

The included `openapi.json` is a shareable snapshot for a developer or hardware supplier. `/api/v1/schema` generates the current schema from the running code.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/v1/adapters` | Registered adapters, USB/serial discovery and setup messages |
| GET | `/api/v1/status` | Connected sensor, latest sample and active scan |
| GET | `/api/v1/state?mode=real` | Workspace scans/model plus `csrf_token` for writes |
| GET | `/api/v1/scan?mode=real&id=...` | Stored scan and raw readings |
| GET | `/api/v1/export?mode=real` | Raw CSV including sensor metadata/extra channels |
| GET | `/api/v1/catalogue` | 50 sourced identities, progress and sensor/feature definitions |
| GET | `/api/v1/catalogue?id=<fragrance_id>` | One perfume and its real reference measurements |
| GET | `/api/v1/catalogue/export` | Committed SQLite reference database snapshot |
| GET | `/api/v1/schema` | OpenAPI 3.0.3 request and firmware schemas |
| POST | `/api/v1/connect` | Connect selected adapter and validate the first reading |
| POST | `/api/v1/disconnect` | Disconnect while no scan is active |
| POST | `/api/v1/start` | Create scan and begin baseline |
| POST | `/api/v1/phase` | Advance phase for a specified scan |
| POST | `/api/v1/finish`, `/api/v1/abort` | Complete or abort a specified scan |
| POST | `/api/v1/train`, `/api/v1/predict` | Train/evaluate or classify an unseen scan |
| POST | `/api/v1/seed` | Load synthetic examples in simulation only |

POST requests use JSON and the `X-Olfy-Token` header obtained from state. For phase/finish/abort, always send both `mode` and `scan_id`. Stale scan IDs and wrong-workspace commands are rejected so a second client cannot accidentally change a different scan. Only one device/recording is active at a time.

For a local web app on port 3000, explicitly enable its exact origin:

```bash
bash start.sh --allow-origin http://localhost:3000
```

```javascript
const base = "http://127.0.0.1:8765/api/v1";
const stateResponse = await fetch(`${base}/state?mode=real`);
const state = await stateResponse.json();
const response = await fetch(`${base}/connect`, {
  method: "POST",
  headers: {"Content-Type": "application/json", "X-Olfy-Token": state.csrf_token},
  body: JSON.stringify({mode: "real", adapter_id: "bme688", config: {address: "auto"}})
});
const result = await response.json();
if (!response.ok) throw new Error(result.error);
console.log(result.sensor);
```

The server remains bound to the Mac's loopback address. This supports local integrations; an iPhone on another device cannot call the Mac's `127.0.0.1`. A phone accessory needs its own transport or an explicitly designed authenticated bridge. Public hosting and multi-user remote access are outside this starter.

## Register another sensor adapter

Implement the `Sensor` protocol in `olfy/contracts.py`: a `SensorInfo`, `read(phase, seconds)` and `close()`. Convert the supplier's readings to canonical units inside the adapter. Never synthesize replacements for a failed real read.

Register it in trusted startup code and pass the registry to the server:

```python
from olfy.adapters import AdapterSpec, default_registry
from olfy.server import make_server
from my_sensor_adapter import MySensor  # Your supplier-specific implementation

registry = default_registry()
registry.register(AdapterSpec(
    "my_board", "My USB board", "real", MySensor, options=("port",)
))
app, server = make_server("data", registry=registry)
try:
    server.serve_forever()
finally:
    server.server_close()
    app.recorder.close()
```

Then another app calls `olfy.connect_sensor("my_board", port="...")`. `MySensor.info.adapter_id` must equal `my_board`, and it must supply `gas_ohm` in ohms for the existing baseline. Registration does not permit arbitrary code loading through the HTTP API.

Changing a compatible transport does not require rewriting the recorder or database. Changing the kind of scientific signal requires new feature extraction, model evaluation and sensor-specific UI where appropriate. Existing model files remain compatible with the unchanged baseline feature version; device and profile differences are still checked.

## Verification and references

Automated tests cover adapter validation, automatic address selection, ambiguous devices, serial handshake/sequence checks, first-read cleanup, loss of connection during recording, detected metadata, stale commands, Python client token refresh, versioned endpoints and explicit browser-origin handling. These use stubs for physical devices.

- [pySerial read and timeout behavior](https://pyserial.readthedocs.io/en/latest/shortintro.html)
- [pySerial port discovery](https://pyserial.readthedocs.io/en/latest/tools.html)
- [Adafruit MCP2221 transport implementation](https://github.com/adafruit/Adafruit_Blinka/blob/main/src/adafruit_blinka/microcontroller/mcp2221/mcp2221.py)
- [Adafruit BME680/BME688 driver API](https://docs.circuitpython.org/projects/bme680/en/latest/api.html)

## Consumer quick capture

The consumer circle uses `POST /api/v1/capture`. Connect and condition the real sensor first. The request uses the same metadata as `start`, with `mode: "real"`, `warmup_ack: true` and `duration_s: 10` (allowed range 5–60). The JavaScript SDK exposes `startCapture(metadata, 10)` and the Python SDK exposes `start_capture(metadata, duration_s=10)`.

Poll `status()` for `active.capture_mode: "quick"`, `active.target_seconds` and `active.phase_elapsed_s`. Recording stops automatically and is saved with status `captured`. Read it with `getScan`/`get_scan`; cancellation uses the existing abort command and preserves partial data. Device faults retain an `error` scan and never substitute simulated data.

These clips are raw acquisition data. They are excluded from the current three-phase model, which only accepts status `complete`. The current USB hardware stays powered and warmed; physical wake from sleep for a future wireless accessory needs firmware support. The API currently starts recording and does not claim to wake an unpowered device.

## Experiment software 1.0 additions

The catalogue and classifier share one feature definition and sensor compatibility key. Catalogue exports now include raw sensor samples and numerical feature rows, joined to perfume IDs by the `perfume_sensor_samples` and `perfume_sensor_features` SQL views. See `SENSOR_DATABASE_MAP.md`.

`GET /api/v1/readiness?mode=real` returns compatible cohorts and collection coverage. Supply a cohort `profile_key` with training when collecting more than one configuration. Predictions include catalogue IDs for linked known classes. Changed heater settings, units or sampling rate cannot silently reuse a model.

`POST /api/v1/bookmark` saves/removes a completed scan with `scan_id`, `saved` and `mode`; `state` returns `saved_scan_ids`. The consumer adapter uses this durable store. `GET /api/v1/backup` produces a complete data snapshot when no scan is active. Restore is a CLI operation into a fresh data directory; see `BACKUP.md`.

`GET /api/v1/model-runs?mode=real` lists preserved experiments; `GET /api/v1/model-run?mode=real&id=<model_id>` returns an immutable model/report with its source dataset digest. `GET /api/v1/health` reports software capabilities and connection status without claiming validated perfume accuracy.


## Preparation endpoints (software 1.1)

`GET /api/v1/setup` checks packages, writable storage, database quick checks, optional driver presence, reference counts and connection status without opening hardware. This is software readiness, not chemical or device validation.

`POST /api/v1/practice` with `{"mode":"simulation"}` runs storage, features, a held-out model, known/unknown predictions, bookmarks and backup/restore inside a temporary dataset. It leaves existing workspaces and models alone and refuses to run during a recording.

`GET/POST /api/v1/plan` loads/saves the experiment plan. POST fields: `fragrance_ids` (2-5 distinct catalogue IDs), `substrate`, `dose`, `drydown_min`, `start_date` (ISO date), and optional boolean `include_unknown_control` (default false). The plan proposes three dates, three fresh replicates per perfume/day, a clean-air control, and optionally an unfamiliar-perfume control each day. These are experiment defaults, not accuracy guarantees. `GET /api/v1/plan/export` exports the proposed checklist. Plans are backed up in real.sqlite3; they do not create raw samples or fingerprints.

The browser SDK exposes `setup`, `practice`, `experimentPlan`, `saveExperimentPlan` and `planCsvUrl`; the Python SDK exposes the corresponding snake_case methods. Existing sensor commands and contracts are unchanged.
