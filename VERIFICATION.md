# Verification

Repository preparation checks completed on **18 October 2026** in a Linux execution environment.

| Check | Result |
| --- | --- |
| Existing Python suite | **50 tests passed** using Python 3.12.14, NumPy 2.3.5 and scikit-learn 1.8.0 |
| Frontend dependency install | Frozen lockfile installation passed |
| TypeScript | `pnpm exec tsc --noEmit` passed |
| Production consumer build | Vite 8.0.5 build passed using Node 24.19.0 |
| Python distribution | Wheel built successfully; consumer entrypoint/assets, catalogue, schema and setup files present |
| Shell and standalone JavaScript syntax | Launcher, publishing helper and Lab/setup scripts passed syntax checks |
| Guided browser practice | All six checks passed: generated storage, shared features, held-out split, known example, unknown rejection and backup/restore |
| Consumer browser flow | Demo result displayed; saving succeeded; saved collection survived clearing browser storage and reloading |
| Browser layout | Setup had no horizontal overflow at 390×844 and 1440×1000 |
| Data separation | Review workspace ended with 50 identities, zero real scans and zero measured references |
| Browser page errors | None during the smoke flow |

The screenshots in `assets/` were captured from the running application after the frontend build. The demo result is a generated signal. The Lab screenshot shows the unmeasured reference catalogue.

The existing suite covers numerical features, dataset split guards, acquisition, sensor contracts, API integration, interrupted recordings, catalogue indexing, backup/restore, workspace locking and experiment planning. Driver tests use software substitutes.

GitHub Actions is configured for Python 3.11/3.12/3.13 and a separate frontend check. Those hosted jobs run after publishing; this document records local checks, not a completed GitHub Actions run. Frontend verification here used pnpm 11.25.0; the repository's existing toolchain configuration and CI use pnpm 10.34.3.

Physical BME688/MCP2221 behavior, the intended Mac, Safari, Bluetooth/accessory firmware and real perfume recognition were not validated by these checks. The next experiment is described in [EXPERIMENT.md](../EXPERIMENT.md).
