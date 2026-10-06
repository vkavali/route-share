# Route share native beta client

This is a native Expo / React Native client for the same local beta API used by the web prototype. It uses native controls and navigation; the embedded WebViews are limited to the Leaflet map picker and route/live map.

## Local setup

Use Node 20.19 or newer. Copy `.env.example` to `.env` and set `EXPO_PUBLIC_API_URL` to the API base. Plain HTTP is accepted only for `localhost`, `127.0.0.1`, or `::1`; use HTTPS for every non-loopback host. The shared beta API is available at `https://route-share-beta.up.railway.app`. For local Android emulator testing, `adb reverse tcp:5000 tcp:5000` makes the loopback development API reachable at `http://127.0.0.1:5000`. A physical phone's loopback points to the phone itself. No iOS or Android device has been tested against the hosted API from this workspace.

Run `npm install`, `npm run sync:shared`, and `npm run start`. The app uses the API's invited development accounts; this is not public registration. Tokens are stored in platform secure storage and sent as Bearer authorization. The API remains authoritative for booking, matching, capacity, safety and location-sharing rules.

Typography is bundled with the app: Manrope for Latin text and Anek Telugu for Telugu, with static weights 400, 500, 600 and 700. The native screens use local font files rather than fetching fonts at runtime. Their SIL Open Font License notices are in `assets/fonts/` and source/checksum provenance is in the repository's `static/fonts/PROVENANCE.md`.

## Native builds

`npm run export:all` type-checks and exports JavaScript bundles for both iOS and Android. This does not compile or sign installable app binaries. The configured bundle/package id `com.routeshare.beta` is a placeholder; choose production identifiers and signing credentials before distribution. Location permission is foreground-only; sharing requires an explicit in-app start and stops on app background, view exit, or server termination.

The EAS `preview` profile remains an internal beta build. The `testflight` profile uses store distribution, increments build numbers, and embeds `https://route-share-beta.up.railway.app` as `EXPO_PUBLIC_API_URL`; local runs continue to use the loopback value in `.env.example`. After an Expo project is linked and Apple signing/App Store Connect access are available, build and upload with `eas build --profile testflight --platform ios --auto-submit`. This repository still has placeholder identifiers (`com.routeshare.beta`) and no linked EAS project; it is not ready to sign or upload until those are replaced/configured. The profile is prepared, but no EAS build or TestFlight upload has been run.

The map uses the same authenticated `/api/places` search provider as the web client, and its OpenStreetMap tile layer requests map tiles from `tile.openstreetmap.org`. GPS samples are sent only to the configured authenticated API. The app does not store GPS samples or start background location tracking. Sharing is explicit and foreground-only. A native instance that started sharing stops its watch and revokes its lease when it backgrounds or leaves the live view. After reload, the app can recover only the signed-in participant's own active stop token from the API and expose an explicit Stop action; it does not restart GPS. The web equivalent passed 7/7 isolated fixture checks with simulated GPS (`work/reload-stop-evidence.json`); this does not verify the native flow, a real trip, or device GPS.
