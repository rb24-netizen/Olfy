# How a perfume connects to what the hardware tracks

The point of contact is an **empirically measured response fingerprint**, identified by the perfume ID and kept with its sensor configuration. A perfume name alone has no known numerical fingerprint.

The recording form selects a `fragrance_id`. The recorder attaches it to a unique `scan_id`, stores the device readings, then extracts the same numerical features the classifier uses. A prediction maps a class back to its `fragrance_id`. It never substitutes fragrance notes or ingredient formulas for measurements.

| Layer | Stored parameters | Connection |
| --- | --- | --- |
| Perfume identity | Brand, exact variant, declared concentration label, source URL | `fragrance_id` |
| Independent measurement | Bottle, sample, collection day, substrate, dose, drydown, notes | `scan_id` → `fragrance_id` |
| Hardware configuration | Device ID, adapter, profile, channel units, heater settings, sampling interval | `profile_key` attached to the scan |
| Sensor curve | Time, phase, gas resistance, temperature, humidity, pressure, heater settings, declared extras | Samples attached to `scan_id` |
| Comparable fingerprint | 12 baseline-normalized resistance features | Feature values attached to `scan_id`, scheme and profile |
| Model result | Candidate class, perfume ID, score, rejection reasons | Class mapping → `fragrance_id` |

## Actual hardware parameters

| Parameter | Unit | Current role |
| --- | --- | --- |
| `gas_ohm` | ohm | Primary measured signal; resistance changes across the exposure |
| `temperature_c` | °C | Recorded environment; inspection, not a classifier feature yet |
| `humidity_pct` | %RH | Recorded environment; inspection, not a classifier feature yet |
| `pressure_hpa` | hPa | Recorded environment |
| `heater_c`, `heater_ms` | °C / ms | Sensor heater settings; part of configuration compatibility |
| `sampling_interval_s` | second | Acquisition interval; part of configuration compatibility |
| `extra_channels` | Adapter-declared units | Preserved raw channels; new feature extraction needed to use them |

The first BME688 configuration has one resistance channel and a fixed heater setting. It does not measure concentrations of individual perfume molecules. These are sensor response parameters, not a reconstructed perfume recipe.

## Shared fingerprint definition

The catalogue and classifier use **`log-resistance-phase-bins-v1`**. For each complete baseline/exposure/recovery scan:

1. Take the median clean-air baseline resistance.
2. Normalize each reading as `ln(resistance / baseline median)`.
3. Divide exposure and recovery into four time bins each.
4. Store the mean in each bin, plus exposure minimum, maximum, standard deviation and the mean of the final three recovery readings.

All 12 features are dimensionless. The database contains their exact names, order, source channel, units and calculation in `feature_definitions`. Raw curves remain available to inspect or to apply a future extractor.

## Searchable SQLite structure

- `fragrances`: 50 sourced identities. No assumed molecular composition or percentages.
- `sensor_profiles`: settings and channel units for each compatible configuration.
- `reference_measurements`: one complete labelled real exposure, conditions, quality flags and its fingerprint JSON.
- `reference_samples`: every sensor reading behind those references, with common numerical channels and the complete original payload.
- `reference_features`: numerical feature values with foreign keys to the measurement and definition.
- `perfume_sensor_samples`: a view joining perfume identities directly to recorded channels.
- `perfume_sensor_features`: a view joining perfume identities directly to the comparison parameters.
- `catalogue_progress`: counts of pending, measured and review-needed entries.

Example lookup after measurements exist:

```sql
SELECT fragrance_id, device_id, profile_key, feature_name, value, unit
FROM perfume_sensor_features
WHERE fragrance_id = 'sephora-p504996';
```

The delivered database has **50 identities, 12 feature definitions and zero measured reference samples/features**. The connection is implemented; its numerical values arrive only when authentic samples are measured.

## Compatibility and identification

The app separates configurations by adapter, declared units, profile, observed heater settings and sample rate. The model checks that configuration, acquisition protocol, phase durations and device before accepting a comparison. Changed substrate, dose or a drydown outside the training range cause provisional rejection. These are applicability guards, not validated chemical selectivity rules.

A model keeps its feature version, settings, perfume class IDs, training/test scan IDs, dataset checksum, parameters and evaluation. Retraining preserves previous runs. A high score on generated fixtures does not establish real perfume accuracy.

Short consumer captures contain exposure-only raw data and cannot be compared to the three-phase model. The app preserves that distinction. A future fast identification mode requires measured short-capture references, suitable features and validation.

The architecture supports new transport adapters and declared extra channels. A different scientific signal, such as an optical spectrum or molecule-specific concentration, needs an appropriate feature extractor and new references; it is not interchangeable with resistance simply because the data can be transmitted.
