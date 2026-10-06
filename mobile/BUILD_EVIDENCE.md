# Native beta build evidence

## Current source — 2026-10-06

- The native sign-in, offer-ride and find-ride screens now use the selected green/ivory reference composition. Locations remain blank until chosen; the two passenger pickup-window fields, one passenger seat, driver seat range 1–6, and detours 0/5/10/15 remain real controls. Password login remains enabled. The safety report keeps its existing category, details validation, report submission and block actions with larger text and controls.
- Native text uses bundled Manrope/Anek Telugu fonts. Body text defaults to weight 500; safety labels and actions use real bundled 600/700 weights. No alternate map provider or new location-sharing behavior was added. Empty maps show a regional view; selected stops and routed journeys still use actual coordinates.
- Current TypeScript check and shared EN/TE/HI locale parity passed. Shared dictionary SHA-256: `4cccf7d8d028381ba5864f14debc862b3134b52f5e4c6151503cbe2e0c50b655`.
- Current iOS JavaScript export passed with `EXPO_PUBLIC_API_URL=https://route-share-beta.up.railway.app`: 754 modules and 11 image/font assets. Bundle: `dist/ios/_expo/static/js/ios/index-05da743e6d751a85eb76b187419de7a2.hbc`, 2,436,449 bytes, SHA-256 `0c85634b4bf2f9ff961a3efe226a6223aef07f506bedd025871d768fb7f666ca`. A separate no-bytecode diagnostic export confirms that hosted API origin is embedded.
- This is **not a signed IPA or TestFlight delivery**. No iOS simulator/device execution or native screenshot comparison has run for these changes. Android has not been re-exported after this native reference update.
- Signing remains unverified: the configured bundle ID is still explicitly marked as a placeholder, no Apple Team ID/EAS project is linked, and the installed EAS CLI reports not logged in. The user reports Xcode is signed in on the Mac. The Mac hostname resolves, but SSH refused the connection when checked; no remote execution tool is available in this chat. Account access must be verified on the Mac before selecting an existing signing identity and building/uploading.

## Earlier checks (historical)

Validated on 2026-10-06 with the project-local Windows Node/Expo toolchain. No global dependencies were installed and no Android SDK or Xcode was installed.

- `npm run sync:shared`, `npm run typecheck`, `npm run check:translations`, and `npx expo install --check` all passed after the latest native UI and shared-copy changes. Expo SDK 54 dependencies are compatible.
- Shared EN/TE/HI dictionary parity passed at SHA-256 `33fdcf5bc676594189762cde905c81c7106b9986fb46afa628deec82a1ad8d74` (`src/generated/i18n.js`).
- `expo-font` loads bundled Anek Telugu weights 400–700 for Telugu text and Manrope 400–700 for English/Hindi. The eight font files and OFL licenses are in `assets/fonts/`; the export includes them.
- With `EXPO_PUBLIC_API_URL=http://127.0.0.1:5000`, `npm run export:all` passed its sync/typecheck steps and exported both JavaScript bundles:
  - iOS: `dist/ios/_expo/static/js/ios/index-645fb4fda2a6a970dcdaa7f88b7556c3.hbc` (2,408,260 bytes).
  - Android: `dist/android/_expo/static/js/android/index-ac1916523d401df7d4e469a49a10ad89.hbc` (2,427,748 bytes).
- These are Expo JavaScript exports, not signed/installable native builds. No iOS simulator/device or Android emulator/device run, native screenshot review, or human Telugu review was performed. Android local API testing requires `adb reverse tcp:5000 tcp:5000` while the API is running; iOS simulator testing requires a Mac with Xcode.
- The live view provides an explicit Stop action for the viewer's own active lease recovered via `viewer_sharing_id` after reload. That reload-to-stop behavior has not been exercised end to end on a device. Leaving the live view or backgrounding the app stops the local GPS watcher and attempts to revoke the known lease; backend expiry remains the fallback.
- The native map keeps its existing OSM tile behavior. The proposed OpenFreeMap theme is not integrated pending approval for sending map viewport requests to that provider; current mapping behavior was not disabled.

- Final native-source check on 2026-10-06: shared EN/TE/HI sync and parity passed at SHA-256 `4cccf7d8d028381ba5864f14debc862b3134b52f5e4c6151503cbe2e0c50b655`; TypeScript passed. A fresh iOS JavaScript export ran with `EXPO_PUBLIC_API_URL=https://route-share-beta.up.railway.app` through Windows Node 20; Expo config reported `apiBaseConfigured: true`, bundled 754 modules and 11 image/font assets, and wrote `dist/ios/_expo/static/js/ios/index-fd74bd13fbfaa795e1a1aeac41544602.hbc` (2,431,569 bytes, SHA-256 `ede5cade1ba57ed601a4b96ecaf9c265c45ec1ab667db24152d01fa4f7d88d27`). A separate no-bytecode diagnostic export confirmed the hosted API origin is inlined in the JavaScript bundle. The Android export listed above predates the latest native-source edits and was not regenerated in this final pass. This is a JavaScript export only, not a signed native build or TestFlight upload.

- After adding native profile editing, opt-in phone sharing, booking chat/list, notifications, and authorized call flow, shared translation key audit found no missing literal keys; locale parity and TypeScript checks passed. Both platform JavaScript exports above were regenerated from this code. These checks do not validate live-device UI, call handling, or a hosted deployment.
