# SeatPal native branding and loading

Implemented locally on 2026-10-13. No native release, TestFlight upload, deployment or physical-device verification is included in this work.

- iOS icon: `assets/seatpal/icon-ios.png`. Android adaptive foreground and monochrome assets use the approved seat mark; ivory background is `#F6F5F0`.
- The OS splash is a static, centered 120px seat mark. `expo-splash-screen` 31.0.13 is the Expo SDK54-compatible native dependency. Its config plugin requires a fresh native build.
- Splash is held at module load, then released on the first laid-out native loading, usable, or error frame. It does not wait for the animation or add a minimum startup duration.
- `NativeTypographyProvider` keeps the startup loader in one full-window position, outside SafeArea, while either existing font or account restoration is pending. Existing error/Retry/Logout handling is retained. The label uses system text until fonts are available.
- Startup uses a shared 4.4-second one-shot clock. After a short transition from the exact OS mark to the approved hero geometry, a single lime cushion persists as vehicle envelopes appear and its backrest folds into the motorbike seat. It settles back at the core if initialization is still pending. Fast initialization removes the loader immediately; font/auth handoff and retry do not replay it.
- Real pending search, request, driver accept/decline/completion and existing generic actions use a compact seat pulse and accessible operation label. Loaded Telugu screens retain bundled Anek Telugu text. No booking status, timeout, retry, API request, or success condition was changed.
- Reduced motion starts conservatively static, respects updates, and ignores late preference queries after unmount. Backgrounding stops animation; foreground resumes only the remaining startup time. Compact pulses stop on unmount/background.

## Local evidence

Commands run from `mobile` with the existing Node runtime:

```
node node_modules/typescript/bin/tsc --noEmit
node scripts/check-native-dependencies.cjs
node scripts/sync-shared.mjs --check
node scripts/test-seatpal-loader.cjs
node scripts/test-native-trip-integration.cjs
node scripts/test-phone-auth.cjs
EXPO_PUBLIC_API_URL=http://127.0.0.1:5060 node node_modules/expo/bin/cli export --platform all --output-dir dist/seatpal-loading-qa
```

The mounted loader test exercises startup continuity, fast completion, reduced-motion races, background/resume/unmount, the single cushion, compact pulse, accessible pending status, first-layout splash release and font-error retry. The actual App-handler fixture exercises delayed and failed search/request, explicit retry, duplicate search/request suppression, driver accept/decline/completion, and no premature success state. Native primitives and responses are mocked; no real booking/SMS action occurs.

TypeScript, translation parity, installed SDK dependency preflight (19 packages), all three mounted scripts, and both iOS/Android Hermes exports passed. Export artifacts use only an explicitly selected loopback QA origin and are not deployment artifacts.

## Still requires native validation

Install fresh iOS and Android release builds to inspect platform icon masks, launch-screen centering, OS→React Native visual handoff, SVG animation and accessibility on native renderers. Repeat with fast/slow/error initialization, reduced motion, background/foreground, and failed trip requests. Metro exports and mocked native component tests cannot establish those results. Expo documents that Expo Go/development builds do not fully reproduce release splash behavior: https://docs.expo.dev/versions/v54.0.0/sdk/splash-screen/.
