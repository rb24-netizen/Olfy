# What remains after experiment software 1.0

The recording, Lab, consumer scan UI, catalogue linkage, feature extraction, training/evaluation, saved collection, model history, backup and restore are implemented. See `SOFTWARE_RELEASE.md` for software verification and `SENSOR_DATABASE_MAP.md` for the perfume-to-hardware connection.

The next useful work depends on physical evidence:

1. Connect the BME688/MCP2221 prototype on the actual M1 Mac. Verify fresh readings, device identity, conditioning and baseline behavior.
2. Collect controlled references for 2–5 authentic perfume variants. Keep dose, drydown, substrate, airflow and timings consistent; include blanks and unfamiliar perfumes.
3. Evaluate on independent collection days. Inspect errors and ethanol/dose effects before expanding toward the 50-entry shortlist.
4. Compare sensor configurations or arrays if one resistance channel does not separate the samples. Extra channels can be stored now; using a new scientific signal needs suitable features and measured data.
5. Develop a short-capture model if rapid identification is supported by measured signals. Current 10-second captures are raw clips, not perfume recognition.
6. Build the compact accessory, its power/airflow arrangement, firmware and wireless protocol. Add a transport adapter and actual wake/readiness behavior.
7. Package and verify a native mobile product after selecting the accessory design.

Optional future software improvements include collection-day cross-validation, batch/device holdouts, environmental features, richer error analysis and calibrated rejection. Their design should follow observed errors, not synthetic scores. No simulated test establishes consumer scent recognition.
