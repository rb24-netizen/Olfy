# Olfy consumer interface

This React frontend was exported from Figma Make and connected to the existing local Olfy API. Its mint scan circle, serif typography and mobile navigation are retained. The mobile layout fills the browser viewport; desktop uses a centered panel.

Normal users run `bash start.sh` from the parent folder. Compiled assets and fonts are included, so Node is not required to launch the app.

For source edits, use Node compatible with the included Vite toolchain and pnpm:

```bash
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit
pnpm run build
```

The build writes into `../olfy/web/consumer`. The Python server serves that build at `/` and keeps the research workbench at `/lab`. Vite's optional development server proxies local API calls to port 8765.

`src/services/device.ts` defines the UI's adapter contract. The backend adapter uses the shared `olfy/web/olfy-client.js` SDK. A separate design-preview adapter is used for file URLs or the explicit preview query; it never operates hardware. Raw captures are saved by the backend and do not fabricate a perfume match. Saved collection bookmarks are stored per workspace in the backend database and included in full backups. Existing browser bookmarks are migrated after connecting. The standalone design preview uses session-only bookmarks.

This is a mobile web interface, not an installed iOS app or a wireless detector implementation. See the project README for physical hardware and recognition limitations.
