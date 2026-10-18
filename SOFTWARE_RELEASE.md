# Olfy preparation update 1.1

Open `Start_Here.html` for the readable starting guide. The connected `/setup` screen checks the workspace, runs an isolated generated-data rehearsal, saves a 2-5 perfume experiment plan, exports a sample checklist, and links that plan to the Lab recording form. Plans survive full backup/restore; they never count as measurements. The launcher adds first-run guidance, dependency-only preparation, local diagnostics, and safe reuse of a running instance serving the same data folder.

The physical sensor and real identification limitations below still apply. The original milestone evidence is retained here; current verification is recorded in `SETUP_VERIFICATION.txt`.

# Olfy experiment software 1.0

The software needed to run the first controlled hardware experiment is implemented and verified with software fixtures. This release does not establish physical sensor compatibility, perfume identification accuracy or a finished wireless consumer accessory.

## Completed software milestone

| Area | Implemented behavior |
| --- | --- |
| Consumer UI | Integrated Figma mobile web design; scan circle, device controls, countdown, cancellation, results and Saved collection |
| Capture backend | Validated sensor adapters; timed 10-second raw captures and full baseline/exposure/recovery recordings |
| Lab | Connection monitor, response curves, sample labels/conditions, raw exports and recorded scan inspection |
| Perfume database | 50 sourced variants; identity → independent measurement → sensor configuration → raw curve → shared feature vector |
| Shared parameters | Canonical units, observed heater settings, sampling rate and the same 12-feature definition used by storage and classification |
| ML workflow | Compatible configuration selection, independent collection-day holdout, unknown rejection and perfume-ID mapping |
| Scientific traceability | Raw samples and searchable features inside catalogue exports; training/test IDs, dataset checksum, settings and preserved model history |
| Data reliability | Backend saved collection, complete SQLite backups, checksum/integrity-checked restore into a fresh folder and one-app-per-data-folder lock |
| Mac setup | Source ZIP with compiled assets, Python launcher, optional double-click command and connection/backup instructions |

## Verification evidence

- **41 automated tests passed.** These cover acquisition, adapter contracts, source identity, numerical features, comparison guards, holdout separation, archive/migration behavior, error preservation, workspace locks and backup/restore.
- **TypeScript checking and production frontend build passed.** Normal launch requires no Node installation.
- **Consumer browser checks passed** at 430×932, 390×844 and 360×780 mobile sizes, plus desktop. Checks include a generated demo, saved collection surviving browser storage removal/reload, warm-up guards, navigation during capture, automatic 10-second capture with a test adapter, cancellation, disconnection and unknown rejection.
- **Lab browser checks passed:** 50 pending identities, reference selection, full reference recording with a test adapter, automatic indexing, raw curve inspection and simulation isolation.
- **Training UI checks passed:** compatible sensor cohort, collection coverage, held-out evaluation, preserved history and unknown-control rejection using generated data.
- **Isolated wheel launch and CLI checks passed:** packaged JSON/schema/assets, initial database creation, HTTP backup, command-line backup/restore and refusal to overwrite an existing dataset.
- The distributed database has **50 identities, 12 feature definitions, zero measured references and zero measured feature values**. Fixture data is confined to temporary test folders and is not included in the deliverables.

Browser and package checks ran in the execution environment, not on a physical M1 Mac or iPhone. Device adapters were tested with controlled software substitutes. Physical BME688/USB behavior, Safari, actual macOS setup and native iOS packaging need on-device verification.

## What you can use now

Unzip `Olfy_Starter.zip`, open the `olfy_starter` folder in Terminal and run `bash start.sh`. Use the consumer screen for the demo and raw captures. Use **Lab → Reference 50** to select a perfume and **Lab → Recognize** to inspect collection coverage and train after compatible measurements exist. Read `SENSOR_DATABASE_MAP.md` for the exact contact between perfume identity and sensor parameters, and `BACKUP.md` before restoring data.

The current USB prototype stays connected for warm-up. The app starts recording; a future sleeping wireless accessory needs actual firmware wake/readiness support.

## The next evidence milestone

Connect the physical sensor, collect authentic independent samples for 2–5 perfumes, and evaluate on a separate collection day with blank/unfamiliar controls. Then decide whether this sensor/configuration justifies expanding toward 50 perfumes. The 10-second consumer clip currently saves a response curve; it does not use the longer reference model to claim rapid identification.
