# Olfy reference catalogue

The catalogue contains **50 perfume variants and zero measured fingerprints** at delivery. It is connected to the recorder used by the consumer app and Lab. Running `bash start.sh` creates `data/catalogue.sqlite3` from the packaged JSON and SQL schema. Existing records and measurements are preserved on restart.

## Where the 50 come from

The selection takes the first 50 distinct eligible perfume variants from Sephora US's all-fragrance category sorted `BEST_SELLING`, across pages 1 and 2. Snapshots were retrieved on **2026-10-14 UTC** (October 13 in Los Angeles).

- [Sephora US, page 1](https://www.sephora.com/shop/fragrance?sortBy=BEST_SELLING)
- [Sephora US, page 2](https://www.sephora.com/shop/fragrance?sortBy=BEST_SELLING&currentPage=2)

This is a retailer-specific shortlist, not a verified worldwide sales ranking. The retailer supplies neither sales counts nor an audited ranking method here. Product order may change. Each entry retains its market, source/product URL and ID, retrieval timestamp and display position. `selection_order` is a list index; `global_sales_rank` stays null.

Sets, samplers, oils, hair/body products, mists and sponsored listings are excluded. Travel duplicates are removed; travel-only listings retain their format and product ID. EDP, EDT, Parfum, Absolu, Intense and Elixir variants retain separate identities. Marketing note phrases are removed from the short names. No percentages are inferred. Where a concentration label is absent, verify the exact bottle variant before recording. This retailer's assortment is not balanced across genders or fragrance families.

`olfy/reference_catalogue.json` contains identities and provenance. `olfy/catalogue_schema.sql` defines the database. No ingredient lists or molecular formulas are substituted for measured signals.

## Sensor fields

| Field | Unit / purpose |
| --- | --- |
| `gas_ohm` | Gas-sensing resistance, ohms |
| `temperature_c` | Ambient temperature, °C |
| `humidity_pct` | Relative humidity, %RH |
| `pressure_hpa` | Pressure, hPa |
| `heater_c`, `heater_ms` | Internal heater setting, °C / ms |
| `extra_channels` | Additional adapter-declared numeric channels and units |
| Device / adapter / profile | Retain configuration provenance |
| Bottle / sample / collection day | Track independent samples and source bottles |
| Substrate / dose / drydown | Retain sampling conditions |

The BME688 configuration is `forced-320C-150ms-1Hz-v1`: a 320°C internal heater setting for 150 ms, around 1 Hz. This is one broadly responsive resistance channel. It does not identify separate gases or determine a perfume recipe. The heater temperature is not the perfume temperature. A changed heater schedule needs a new profile and compatible reference data.

A complete reference scan produces **12 dimensionless features**: four exposure bins, four recovery bins, exposure minimum/maximum/standard deviation, and recovery endpoint. Normalization is `ln(gas_ohm / median clean-air baseline gas_ohm)`. Temperature, humidity and pressure remain attached for inspection; this first classifier does not use them as inputs. Extra channel types need suitable feature extraction and evaluation.

Each reference scan retains its own feature vector, device, profile, units and conditions. The app does not average unlike devices or sampling conditions into one perfume signature. `reference_measurements` holds the features, per-phase channel statistics and quality flags. `reference_samples` includes the actual sensor readings inside the catalogue export as well as their originals in `real.sqlite3`; `reference_features` stores searchable numerical feature values. The SQL views `perfume_sensor_samples` and `perfume_sensor_features` join those parameters directly to each perfume ID. `sensor_profiles` describes configurations. `catalogue_progress` shows pending/measured status. Invalid feature extraction leaves a null vector with `needs_review` status.

## Recording workflow

1. Open **Lab → Reference 50** and click **Record** beside the exact perfume variant.
2. Connect the real sensor. Condition/warm it and check the clean-air baseline.
3. Use an authentic sample. Enter bottle ID, collection day, substrate, dose and drydown. Confirm warm-up when ready.
4. Record baseline → exposure → recovery with the same sampling arrangement. Starting targets are 30/60/90 seconds. Eight readings per phase is only a software completeness guard.
5. Finish. Raw readings stay in `real.sqlite3`; features and metadata are indexed in `catalogue.sqlite3` automatically.
6. Use **Reference 50 → View** to inspect the measurements, quality flags and raw curve. **Download database** exports the current committed SQLite snapshot.

Simulation, interrupted/aborted recordings and consumer quick captures do not populate perfume reference fingerprints. Unknown and blank controls are custom samples without a catalogue identity; they are still needed to evaluate rejection. Short captures remain raw clips and are excluded from the three-phase classifier.

Start with **2–5 perfumes** to test whether this hardware produces reproducibly different signals, then expand toward 50. Training requires at least three training exposures per label across two training days, plus every label on a separate held-out day. That is a software minimum, not evidence of consumer accuracy. Additional repeats, bottles/batches, devices, environments, drydown states and unknown controls will be needed. One usable scan changes progress to `measured`; it does not establish accurate identification.

## API and database download

| Method | Endpoint | Result |
| --- | --- | --- |
| GET | `/api/v1/catalogue` | Identities, progress, sources and sensor/feature definitions |
| GET | `/api/v1/catalogue?id=<fragrance_id>` | One identity and its reference measurements |
| GET | `/api/v1/catalogue/export` | Committed SQLite snapshot, including WAL writes |
| POST | `/api/v1/start` | Real known reference scan; provide `fragrance_id` and the server fills the canonical label |

Python: `client.catalogue()` / `client.catalogue(fragrance_id)`. JavaScript: `client.catalogue()` / `client.catalogue(fragranceId)`. The existing local token, device connection, phases and failure handling apply. OpenAPI includes the new routes.

The delivered **Olfy_Reference_50.sqlite3** file is an initial snapshot containing no raw scans or measured vectors. Updated catalogue exports include the sensor curves and features after collection. The running app maintains its own database and exports updated snapshots after recording.

The classifier and catalogue share feature version `log-resistance-phase-bins-v1`. Compatibility keys include adapter, declared units, profile, observed heater settings and sampling interval. Lab groups compatible recordings and lets you select a cohort for training. See `SENSOR_DATABASE_MAP.md` for the schema and parameter definitions.
