# Olfy experiment software 1.1

A consumer scan prototype and local research workbench for collecting scent-sensor signals and testing whether they distinguish a small set of perfumes. Runs without hardware in an explicitly labeled demo workspace.

**This is working research software, not a trained perfume identifier.** The included demo curves are artificial. They contain no measurements of Oud Wood or any other fragrance. Real identification accuracy remains untested.

**What this ZIP is:** the complete source project, including your Figma-designed React consumer interface connected to the sensing backend, and the separate research Lab. Compiled frontend assets are included, so launching the app does not require Node. The earlier green dashboard on port 8000 remains a separate application; its connector instructions are in [FRONTEND_CONNECTION.md](../FRONTEND_CONNECTION.md).

## Start here

Open **Start_Here.html** in the extracted folder for a readable guide. Double-click **Start_Olfy.command** to open the connected setup screen at `/setup`. It checks dependencies/data integrity, runs a disposable six-step pipeline rehearsal, saves your first sample plan, and links to the consumer app and Lab. No Markdown reader is needed.

The optional **Check_Olfy.command** prints local diagnostics. `bash start.sh --prepare` installs dependencies without starting the server. `bash start.sh --hardware --prepare` prepares the optional BME688 packages before delivery. The launcher reuses an existing Olfy instance only when both the port and resolved data folder match.

Saved experiment plans live in the real workspace settings table and travel with full backups. They do not create measurements. In **Lab → Real sensor → Record**, the planned-sample selector fills perfume identity and conditions, uses today’s actual collection date, generates a fresh sample ID, and leaves the bottle ID for you to enter. Review actual conditions before recording.

## Run on your M1 Mac

1. Unzip `Olfy_Starter.zip`. Put the `olfy_1_1` folder in Downloads.
2. Open Terminal and paste:

```bash
cd ~/Downloads/olfy_1_1
bash start.sh --setup
```

The launcher creates a Python environment, installs two software dependencies and opens **http://127.0.0.1:8765/setup** on first launch. The first run needs internet access to download dependencies. Later runs reuse that environment and skip installation when requirements are unchanged. No accounts, API keys or Node installation are needed.

If Terminal reports that a compatible Python is missing, install **Python 3.12 or 3.13 for macOS** from [python.org](https://www.python.org/downloads/macos/), reopen Terminal and run the commands again. The starter accepts Python 3.11–3.13. Apple's older system Python may not be suitable. If the folder is somewhere else, type `cd `, drag the unzipped folder into Terminal and press Enter before running `bash start.sh`.

Keep Terminal running while using the dashboard. Press **Control+C** to stop. Recorded data stays in `data/` inside the project folder. Use **Lab → Dataset → Full data backup** to preserve recordings, fingerprints, saved collection and model history together. Finish or abort an active scan before taking the backup. See [BACKUP.md](../BACKUP.md).

If port 8765 is occupied:

```bash
bash start.sh --port 8766
```

You can also double-click `Start_Olfy.command` on your Mac to launch through Terminal. The Terminal commands above remain the fallback if macOS blocks an unsigned downloaded script.

## Consumer scan page

The app opens on the React interface exported from Figma, with its dark forest background, serif typography, mint circle and Discover/Saved/Device navigation. Its device service uses the existing shared browser SDK and API. The exported fake device and fixed battery reading have been replaced by backend status; battery is displayed only if a sensor supplies a valid `battery_pct` extra channel.

Tap the circle in **Demo** mode to load the artificial reference dataset, train a demo model if needed, and classify an unseen generated example. Results stay labelled as demonstrations and never use real perfume brand names. Existing simulation models are preserved. Demo results come from the backend's stored generated scans, not a simulated 10-second physical measurement. The advanced settings include a generated unknown-control example.

Use **Device** to choose **Real sensor** and connect the BME688 or a board implementing the USB serial protocol. Confirm conditioning and warm-up once the device is ready. Hold the sample near the sensor and tap the circle: the backend records for **10 seconds**, supplies the countdown and automatically saves the raw capture. Navigating between tabs does not cancel a running capture. Refreshing the page recovers an active recording from backend status. Continue longer reference recordings in **Lab**.

The result screen plots the recorded resistance signal. **Save to collection** adds its ID to the **Saved** screen. Collection bookmarks persist in the backend database, separately for real and demo workspaces, and are included in backups; raw recordings always stay in the backend database, including unbookmarked captures. Save/reopen does not turn a raw capture into a perfume identification.

Quick captures have status `captured`, separate from the `complete` baseline/exposure/recovery scans used by the current classifier. The app shows the saved reading count and makes **no perfume identification** from these short clips. A short-capture feature pipeline and model need real reference data and validation. Use **Lab** for the existing 30/60/90-second controlled collection and classification workflow.

The current USB sensor remains powered and sampled between scans to maintain warm-up; tapping the circle starts a timed recording. It does not wake an unpowered device or implement wireless sleep/wake. The future phone accessory will need a firmware wake command and a readiness response behind the same app action. The 10-second period is a software capture setting, not evidence that perfumes can be identified in 10 seconds.

Open **Settings → Open research Lab**, or visit **http://127.0.0.1:8765/lab**, for the full testing interface. Both screens use the same backend, recorder and datasets. The previous plain HTML scan interface is available at `/classic`.

You can open `Olfy_Scan_Preview.html` directly in Chrome for a self-contained interactive design preview. Fonts and scripts are embedded; it makes no sensor/API calls and presents illustrative results as design demonstrations. The connected app uses the same compiled UI with the real API adapter.

**Mobile format:** this is a responsive mobile web interface, not an installed iOS app. It fills a phone viewport and appears in a centered panel on desktop. The current backend binds only to the Mac's loopback interface and controls a USB sensor, so it is not yet a phone-to-wireless-detector system. Native packaging and accessory firmware/transport are separate future work.

## Try the full lab workflow now

The **Reference 50** tab contains the sourced perfume catalogue. All 50 start
with measurement status **pending**. Select **Record** beside a perfume to fill
its exact label in the real recording form. See [CATALOGUE.md](../CATALOGUE.md) for
the source scope, sensor fields and collection workflow.

1. Open **Lab**. Keep **Simulation** selected. Click **Load demo dataset**.
2. Open **Dataset** and inspect a response curve. The dataset contains 68 artificial scans: five labels, four collection groups, plus unknown and clean-air controls.
3. Open **Recognize**. Select `demo-day-4` as the held-out day and click **Train & evaluate**.
4. Select a held-out scan and click **Identify sample**. Training scans are excluded from that selector.
5. Export the raw CSV from Dataset if you want to inspect readings in a spreadsheet.

Simulation scores verify the software workflow only. The deliberately simple generator makes arbitrary curves; it is not a physics model of perfume evaporation. Rejected known demo scans are visible in the confusion matrix and count as identification errors.

To try live recording without a sensor: start a simulation scan, wait for baseline readings, click **Expose sample**, then **Return to clean air**, then **Finish scan**. The starting protocol is 30/60/90 seconds. Each phase requires at least eight readings, but that minimum is only a software completeness guard. Consistent, longer phases are needed for comparable experiments.

## When your hardware arrives

**Updated connection setup:** run `bash start.sh --hardware` to install the optional drivers and open the app in one command. Keep **Auto address** selected for the BME688. Device identity/profile are now attached automatically after a validated first reading. USB serial boards using the Olfy JSON protocol are also supported. See [INTEGRATION.md](../INTEGRATION.md) for the Python client, versioned API, firmware format and custom adapters.

This adapter targets the **Adafruit BME688 breakout + MCP2221A USB bridge + STEMMA QT cable** discussed for the Mac prototype. It does not target a Bluetooth accessory or Bosch's multi-sensor development kit.

1. Stop Olfy, connect the breakout to the bridge with the QT cable, and plug the bridge into your Mac with a USB **data** cable.
2. From the project folder, install the optional hardware dependencies:

```bash
.venv/bin/python -m pip install -r requirements-hardware.txt
bash start.sh
```

3. Open **Device → Real sensor → Connect sensor** for automatic BME688 detection. Lab also offers explicit `0x76`/`0x77` selection when needed.
4. Condition and warm up the sensor in clean air. Adafruit recommends approximately 48 hours for initial conditioning and 30 minutes on subsequent uses. The connected monitor keeps taking measurements between scans. Use a stable baseline and the manufacturer's current guidance; a running timer does not establish readiness.
5. Enter the actual perfume label, bottle ID, fresh sample ID, collection day, substrate, dose and drydown. The connected device ID is filled automatically. Confirm conditioning/warm-up before starting a real scan.
6. Record the three phases with consistent sampling conditions. See [EXPERIMENT.md](../EXPERIMENT.md).

**The hardware adapter has been checked against the documented API, but has not been tested on a physical BME688 or an actual Mac in this build.** Connection errors stop recording. The real workspace never substitutes artificial readings. After connection, verify that resistance changes on exposure and returns toward baseline before attempting classification.

The default profile is one forced measurement around 1 Hz with a **320°C, 150 ms heater setting**. That is the internal sensor heater, not an exposure temperature for the perfume. This is one resistance channel at one heater setting, not Bosch AI-Studio's multi-temperature gas scan. Adding a different heater schedule changes the measurement protocol and requires a separate dataset/model.

## What is implemented

| Part | Behavior |
| --- | --- |
| Acquisition | Baseline → exposure → recovery; raw resistance, temperature, humidity, pressure, timing and sample metadata |
| Storage | Separate simulation and real SQLite databases; incomplete scans preserved and excluded from training |
| Reference catalogue | 50 sourced perfume variants; automatic indexing of complete labelled real reference scans; device/profile/conditions retained; SQLite download |
| Inspection | Live and recorded response plots; basic noise/recovery flags; raw CSV export |
| Features | One vector per complete exposure; baseline-normalized log resistance; time bins and response statistics |
| Classification | StandardScaler + logistic regression; parameters saved as inspectable JSON |
| Evaluation | Whole collection day held out; scaler, classifier and class distances fit on training scans only |
| Rejection | Provisional checks for weak signal, low score/margin, unusual class distance, incompatible timings and unseen device |
| Interfaces | Consumer quick capture; sensor contract/registry; BME688 and USB serial adapters; `/api/v1/` API with OpenAPI schema and a dependency-free Python client |

Unknown controls and blanks never train the known-perfume classifier. A class needs at least three training exposures across two training days; the held-out day must contain all known labels. The app prevents a scan from being presented as unseen if it was used for training and blocks the same sample ID appearing on both sides of the split.

The reported **known identification rate** counts rejected known scans as errors. **Coverage** counts known scans accepted. **Accepted accuracy** describes only that accepted subset. **Control rejection** describes the available unknown/blank controls; it says “Not tested” when none exist. Scores are uncalibrated outputs, not trustworthy confidence percentages.

The model's fixed rejection thresholds are research defaults. They have not been validated for actual perfumes. Do not adjust them using the test day and then report that same day as an independent final test. A three-day experiment is a starting check, not evidence of consumer reliability.

## What still needs evidence

This sensor does not identify individual molecules or determine a perfume recipe. The code does not separate ethanol from fragrance chemicals. Baseline normalization removes an offset; it cannot recover chemical information the sensor did not capture. Similar perfumes, concentrations and drydown states may produce overlapping signals.

Temperature/humidity are recorded for inspection but are not classifier inputs in this first model. Humidity and environmental conditions still affect resistance, so they must be varied and tested. Wrist/clothing sampling, mixtures, multiple bottles/batches, reformulations, aged samples, additional devices and changing airflow are not established by a controlled blotter experiment.

See [BUILD_NEXT.md](../BUILD_NEXT.md) for the coding tasks you can start now and the steps that depend on measured data.

## Experiment software release

The software milestone is complete: acquisition, inspection, catalogue linking, compatible feature extraction, training/evaluation, durable saved collection, model history and backup/restore. All 50 perfume entries remain awaiting physical measurements. Read [SOFTWARE_RELEASE.md](../SOFTWARE_RELEASE.md) for acceptance evidence and [SENSOR_DATABASE_MAP.md](../SENSOR_DATABASE_MAP.md) for the exact perfume-to-sensor link.

## Developer commands

```bash
# After the first launcher run:
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m olfy --no-browser --port 8765
```

The core software uses only Python's standard library plus NumPy and scikit-learn. Hardware transports use optional dependencies. The browser UI uses local HTML/CSS/JavaScript. Model files use JSON, not Python pickle. The server binds to 127.0.0.1; other local browser origins can be explicitly allowed with `--allow-origin`. It is intended for one local research user, not public hosting.

Verification includes TypeScript checking and a production React build, backend/model/adapter tests, and browser tests against the real local API. Browser coverage includes responsive layouts, generated demo results, saved collection persistence, warm-up guards, automatic 10-second capture with a test sensor, cancellation, disconnect and unknown-control rejection. The standalone preview is checked separately. Physical hardware, Safari and macOS execution still require on-device verification.

## References for the adapter and evaluation

- [Adafruit BME688 breakout and conditioning guidance](https://www.adafruit.com/product/5046)
- [Adafruit BME680/BME688 Python driver API](https://docs.circuitpython.org/projects/bme680/en/latest/api.html)
- [MCP2221 setup on macOS](https://learn.adafruit.com/circuitpython-libraries-on-any-computer-with-mcp2221/mac-osx)
- [scikit-learn group-based evaluation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.LeaveOneGroupOut.html)

No external service is contacted by the running application. Installing dependencies downloads packages from Python's package index.
