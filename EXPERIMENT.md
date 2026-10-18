# First measured experiment

The first question is narrow: **can this device distinguish 2–5 selected perfumes on fresh paper samples under a consistent collection protocol, on a separate day?** Success here supports the next experiment, not identification of every perfume from a wrist.

## Prepare now

- Pick authentic samples. Start with 2–3 meaningfully different perfumes. Record exact name, concentration (EDP/EDT), bottle/source ID and any known batch information.
- Assign a permanent device ID. Use the same sensor and heater profile for the first experiment.
- Use a fresh blotter or independent sample for each scan and give each a unique sample ID. Bottle ID stays the same across samples from that bottle.
- Define fixed dose, drydown, sampling distance, headspace container, exposure time and clearing method. Avoid spraying liquid onto the sensor. Record changes to the protocol.
- Pick a safe, consistent blank and unfamiliar-perfume control. Controls check whether the app is forcing a known label on other signals. Ethanol-only controls would be useful for the solvent confound when they can be handled appropriately.

## Collect with the sensor

1. Condition and warm up the connected sensor according to its manufacturer's guidance. Inspect a stable clean-air baseline.
2. Record clean air for a starting target of 30 seconds.
3. Present the sample using the same chamber, distance and airflow each time. Record a starting target of 60 seconds.
4. Remove the sample and return to clean air. Record at least 90 seconds, and extend clearing if necessary. Do not start a new scan while the prior perfume still dominates the baseline.
5. Complete and inspect the scan. An unstable baseline, truncated acquisition or inadequate clearing needs attention before reuse.
6. Repeat with fresh samples, randomizing perfume order. Every perfume must appear on every collection day. Use the real date as group ID; several runs on the same day should remain in the same group.

These timings are a proposed starting protocol. Adjust them based on response/recovery behavior, then collect a consistent dataset for that protocol. The model rejects exposure/recovery durations differing by more than 25% from its training median. This is a coarse consistency rule, not a scientifically calibrated bound.

## Small first dataset

For three perfumes, a useful first collection is **five fresh exposures per perfume per day on three days**, plus blank and unknown controls on each day. That gives 45 known scans and a separate day available for a first evaluation. Five repeats and three days do not establish broad product accuracy; they help reveal whether there is a repeatable signal at all.

Use day 1 and day 2 for training. Keep day 3 unseen while selecting features and thresholds. Test once and preserve the report. If you adjust the design after examining day 3, collect a new day for the next independent test.

Do not split the individual one-second measurements randomly into training and testing. Those measurements come from the same exposure and are correlated. The app deliberately extracts one vector per completed scan and holds out a whole collection group.

## Decide what the result supports

Look at misidentified and rejected known samples, coverage, and false acceptance of controls. Inspect whether signals differ mostly by dose, humidity, ethanol strength or drydown rather than perfume identity. Collect dose/drydown variations to test that possibility. Repeatedly rejecting one fragrance may mean the chosen sensor/protocol does not capture enough useful information.

Only after the controlled test is repeatable should you expand to similar perfumes, additional bottles, varied humidity, other devices and skin/clothing samples. Treat each as a new evaluation question. Measure with the hardware you intend to ship, since fingerprints may change with sensor type, heater settings and sampling geometry.
