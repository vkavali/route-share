# Route Share — approved Higgsfield implementation review

Reviewed locally on 7 October 2026 (America/Chicago). This report supersedes the earlier home/search-only assessment. Historical evidence remains in `outputs/higgsfield-ui-refresh/previous-design-qa.md` and `work/refined-search-qa/`.

## Result

**Working local web implementation is available for review; the exact native source built and installed in the iOS simulator; launch, runtime and iOS/Android visual verification remain pending. Nothing has been committed, pushed, deployed or uploaded to TestFlight in this UI task.**

Review app: http://127.0.0.1:5121/?lang=te#/login (English is available in the header). This is a local development database with development accounts and real OSRM road routing, not a public paid pilot. The separate reference gallery at http://127.0.0.1:5116/ contains generated studies, not the running app.

## Product and behavior

This product serves people finding a seat on an intercity trip, and private owners offering spare seats on a trip they already planned. The recurring job is finding a compatible route/time and receiving a clear, persisted acceptance. The existing implementation—not generated sample content—defines permissions, inventory, accounts and supported actions.

The approved green/ivory design has been applied to shared navigation and language controls, login/profile, search and results, seat review/request, owner requests and journeys, bookings, live consent/sharing, completion, ratings and safety. Native App/CommunityScreens use the same reference family and shared translations. Generated empty-state illustrations are actual app assets; generated maps, text, prices, identities and buttons are not embedded as functioning screens.

| Action | Preserved or improved guarantee | Empty/error/slow behavior |
|---|---|---|
| Choose pickup/drop and search | Confirmed map points, editable pickup window and server-computed matches; exact place data remains stored unchanged | Missing points stay on form; incomplete provider result differs from no matches; duplicate slow submit disabled; Back retains draft |
| Review and request | Real driver/vehicle/check status, meeting points, estimate and actual seat request | No fake availability, verified badge or live payment; errors do not become successful bookings |
| Owner offers/accepts | Real preview/publish and server-side acceptance/capacity check | Role restriction and validation retained; pending is visibly different from accepted |
| Read/send messages | Accepted-participant authorization and persisted conversation | Empty conversation remains usable; outsider access stays denied |
| Share location | Explicit consent; accepted booking scope; existing freshness, expiry, stop, arrival and completion behavior retained | Denied/stale/waiting states remain distinct; stale marker can render grey; Stop is visible above mobile navigation |
| Complete/rate/report | Persisted trip/segment state and existing eligibility checks; private report receipt | Cannot rate early; invalid report remains editable; no emergency-dispatch claim |
| Change language/profile/account | EN/తెలుగు controls preserve drafts; Hindi retained; profile changes persist; sign-out revokes access | Wrong password stays signed out; stale-tab actor changes cannot authorize a new user's write |

## Fidelity and functional adaptations

References are archived in `outputs/higgsfield-ui-refresh/originals/` with the manifest, exact generation history and review notes. All 51 images and 12 motion studies are archived; those counts are not claims that 63 product screens or animations were implemented.

- **Type and spacing:** shared readable text, compact branding, consistent field/action heights, balanced gutters, rounded white sheets and forest/lime emphasis. English/Telugu layouts were checked at 375/390/430px and desktop where relevant. Physical-device font rendering and large accessibility text are not verified.
- **Layout:** real maps above results/trip sheets; clear person, route, status and action groups; expanded review before requesting; compact My trips entries; role-aware navigation. Mobile bottom space prevents actions being trapped underneath navigation. Active Stop sharing is a persistent control above that navigation.
- **Assets:** four selected illustrations were cropped/resized from inspected originals into lightweight web and density-aware native assets. See `outputs/higgsfield-ui-refresh/implementation-assets.md`. Each is used only where its actual state exists; preparing an asset does not create a document-review or voice-retry workflow.
- **Maps:** real provider geometry and map attribution remain. Search optionally exposes only the passenger's estimated road segment. It never returns the full proposed driver corridor, another participant's waypoint/schedule metadata or a live location. Missing/ambiguous geometry yields pins and no invented connecting line. Accepted/live/completed maps do not fall back to search estimates.
- **Copy:** shared English/Telugu/Hindi catalogs remain in sync. Exact known city labels are translated for display even when road snapping changes coordinates; custom labels remain verbatim. Map-tile labels and arbitrary upstream place names are not guaranteed Telugu. Native-speaker review is still needed.

Intentional differences from the images: the real pickup window has two editable date/time values; the beta permits one requested seat; phone GPS is inside the existing picker; web has no decorative inactive microphone. Native voice keeps its existing implementation. Static motion studies are references, not proof of native animation. Existing staff operations are retained; payments, refunds, identity-document onboarding and approval controls are not fabricated from mockups.

## Verification evidence

See `work/higgsfield-implementation/integration-report.md` for exact runs, screenshots, source guards and later targeted corrections.

- **45 end-to-end behavior checks**: independent English and Telugu owner publish → passenger search/review/request → owner acceptance → persisted chat → explicit live consent/start/stop → boarding/segment/trip completion → rating/report → profile save/sign-out. Empty, wrong input, slow provider, Back, roles and two-tab actor switching were included. Zero browser page errors.
- The initial consolidated run detected a concurrent live CSS edit. Its original FAIL source-guard status is preserved honestly; subsequent targeted live and Stop-dock captures cover that delta instead of rewriting history.
- **19 Stop-dock checks** include top/bottom viewport geometry at 375/390/430 in both languages plus actual Start, peer disclosure, normal Stop click and peer removal. Additional focused live tests covered fresh/grey stale/expired markers and automatic end states.
- **233 backend tests passed; 4 optional PyAV checks skipped.** These cover the existing suite plus passenger-route geometry/privacy regressions. Skipped checks are not counted as verified. Preview tests prove original-coordinate clipping, inward endpoint trimming, fail-closed invalid/ambiguous data, excluded driver prefix/suffix and private metadata, no new provider calls, and authoritative committed route after acceptance.
- **4 focused route-preview UI/privacy checks** prove the passenger-only line and a single map attribution; sparse geometry retains a valid match but shows no estimated line/caption.
- **Real-provider verification:** a separate server at 5121 uses the existing public OSRM provider, actual place search, real local HTTP and SQLite. English and Telugu publish/search/review/request passed with approximately 3,900 returned road vertices per preview and no page errors. There is no live traffic, physical road survey or human GPS claim. See `real-road-preview-evidence.json` and `real-road-final-capture-evidence.json`: the final capture passed 9 checks, 56 asset responses without errors, 9 matching served hashes and 35 unchanged source hashes. The two development offers are time-bound and will expire under normal app rules; users can create new future offers.
- **Native source:** shared translation parity, TypeScript, mounted App/voice request flows, 28 picker checks and 30 state checks passed. Valid/invalid/unflagged road previews were exercised. These do not establish current simulator pixels, physical microphone behavior or iOS/Android visual parity.

Parent visual review inspected actual EN/TE login, road results, and the Telugu active Stop dock. Screen owners reviewed their actual profile, booking, safety, completion and live states against the references. The smaller results map, estimate-caption stacking, visible single attribution, city-label and success-notice corrections passed targeted recaptures. Parent reviewed final real-road English and Telugu results: the first driver and seat availability are visible above the navigation. This does not imply another whole-suite run.

## Native handoff and remaining blocks

The final source package and its current digest/manifest are in `outputs/route-share-higgsfield-ui-review.*`. The 394 MB generated-reference archive, dependencies and secret files are excluded. Source packages are for local review, not signed distribution binaries.

On 8 October, after the user explicitly approved this exact transfer, the Mac received the 39,879,593-byte source archive (SHA-256 `d5b62605c96ff6ff0338fed5e5e037792ef447e3958853b2ae6d82a59feb984e`). The trusted connected Mac chat verified the complete archive hash and all 234 source-manifest hashes, then extracted `/private/tmp/route-share-higgsfield-ui-d5b62605`. Direct WSL TCP had timed out; the Windows TCP relay reached the same approved Mac while retaining SSH and the verified pinned host key. The existing restricted login key was expired, so the Mac narrowly renewed that same key for 15 minutes after the direct user approval, then restored the original expired entry after delivery. Temporary access is closed. No private key was copied and no password authentication was used.

The trusted Mac chat confirmed **Xcode Release simulator BUILD SUCCEEDED**, `codesign --verify --deep --strict` passed, and `simctl install` exited 0 with the app container resolving on iPhone 17 Pro / iOS 26.3 (`A706E601-709C-432B-9BB7-0564E0EA2F64`). Identity is `com.vkavali.routeshare`, version 0.1.0, build 2. All 234 source hashes remained unchanged after the build. Translation parity, TypeScript, 44 voice tests, 28 picker checks, 32 travel-draft checks, 35 backend mobile-auth/route-preview tests and actual isolated-API sign-in/bootstrap/logout passed. These source/mock/HTTP checks do not prove native audio or screen behavior.

This is a **local-QA-only** app containing `http://127.0.0.1:5060` and no production origin; its isolated API has voice disabled. `main.jsbundle` is 2,628,454 bytes, SHA-256 `b71377481e6c95ddc34477fe1185c6c3297fc3a7ac20c646268949c8e44bbabe`. It must not be uploaded as a distribution build. Native launch, screenshots and crash checks were **not performed**: the required Mac computer-control tool reported the desktop locked. No `simctl launch`/screenshot denial was observed or attempted. Unlock and permitted native runtime/EN/TE visual testing, physical microphone/device checks, and separate Android verification remain outstanding. No TestFlight upload occurred. Exact Mac evidence paths and handoff records are in `work/higgsfield-implementation/native-source-transfer-evidence.json`.

## Assumptions and deliberate cuts

The user's approval selects the latest green/ivory Higgsfield family, not the scenic travel UI or purple promotional study. Existing real behavior and privacy restrictions take precedence over sample imagery. Road previews are estimates and full native appearance remains unverified. No new commercial/private-owner eligibility, legal, insurance or payment approval is assumed.

Keep decorative leaf backgrounds, fake 3D maps, unsupported payment/document buttons and large generated wordmarks out of the working flows. They do not improve the current search/request/accept job. The user’s no-commit-without-approval restriction remains in force.

**Final result: local web review available; exact-source iOS simulator build and install passed, while native launch/runtime/visual verification and distribution remain pending.**

## Neutral concept 3 public landing QA — 14 October 2026

### Result

final result: passed

### Source and rendered comparison

The selected source target is `/mnt/c/Users/vkava/.codex/generated_images/01a111c4-905e-7c52-a5af-7f803111e276/exec-b595ec45-fa1a-4107-a9d9-762582188e08.png` (830×1896 px). The implementation was captured from `http://127.0.0.1:5354/welcome?lang=en` at 390×844 CSS px, deviceScaleFactor 1, anonymous, top of page. The side-by-side comparison is `output/playwright/combined-design-qa/neutral3-comparison-390.png`: source normalized proportionally to 390 px width and cropped to the top 844 px; implementation remains 390×844 px.

The rendered page carries the target’s search-first hierarchy, charcoal CTA, neutral Hyderabad illustration, and restrained blue route accent. The full-width two-line heading and both route inputs/Find CTA remain readable before the illustration. The current implementation puts the animated seat/car/bike mark beside the offer row rather than beside the target’s wordmark; the city art begins around y608 at EN390 and y576 at TE390, while the generated target places it earlier. These differences are accepted for the current concept 3 composition; the CTA remains visible and the supported route labels are explicit.

### Responsive and interaction checks

Screenshots inspected: `output/playwright/combined-design-qa/neutral3-en-1440.png`, `neutral3-en-320.png`, `neutral3-en-390-final.png`, `neutral3-te-320-verified.png`, and `neutral3-te-390.png`. The post-fix 320 px Telugu document has `clientWidth=305` and `scrollWidth=305`; the header wordmark stays on one line, the language controls are 44×44 px, route inputs are 16 px type / 49 px high, and the 51 px Find CTA is visible. EN/TE 390 and EN 1440 also have no horizontal document overflow; EN/TE mobile headings, route labels and art fit the measured viewport.

Five journey stage links are present; selecting Arrive updates the URL to `#stage-arrive`. The visible vehicle animation exposes a running Web Animation; the replay control sets `aria-pressed=true` and reaches a stable paused timeline after the normal frame scheduling interval. Emulating reduced motion hides replay and cancels the animations. The local browser matrix reported zero page errors and zero failed requests.

The real EN landing search handoff was also exercised with the isolated local passenger fixture. Submitting Kondapur → Airport reached login; after passenger sign-in the app opened `#/search-form` with those labels preserved, all four route coordinate fields blank, and the “Choose both locations on the map before continuing” note visible. Submitting before exact map selection stayed on the route and sent zero `/api/search` requests. No external services were contacted.

### Phone preview export

The existing allowlist exporter serves eight public pages (EN/TE welcome, FAQ, terms and privacy) and 14 referenced static dependencies. The current manifest SHA256 is `760ecdf9d64b916aafcf29cbf8344f15b235a407bd4e912325498e46a83bf89a`. EN/TE pages and `neutral-hyderabad.webp` returned HTTP 200 through the existing phone tunnel; `/static/app.js`, `/api/bootstrap`, and unsupported query parameters returned 404. Exported pages preserve body classes and carry `data-public-static-preview="true"`; static EN/TE notes tell users to enter route labels after signing in. The static Find CTA targets plain live SeatPal login without a serialized route intent; the external navigation was intercepted before network access. The preview is a public presentation only; no app/API or deployment was exposed.

Phone preview: [English](https://whole-provide-constant-shopzilla.trycloudflare.com/welcome?lang=en) · [తెలుగు](https://whole-provide-constant-shopzilla.trycloudflare.com/welcome?lang=te). The allowlist uses `Cache-Control: no-store`; adding a cache-buster query is intentionally rejected.

### Full-width split and seated-mark correction QA — 14 October 2026

This supersedes the centered concept 3 composition above. Final screenshots were captured from a fresh local Flask render at 1440×1000, 390×844 and Telugu 320×780, then visually inspected: `output/playwright/final-fullwidth/final-structural-en-1440.png`, `final-structural-en-390.png`, `final-structural-te-320.png`, `final-stage-find-desktop.png`, `final-stage-check-desktop.png`, `final-stage-agree-desktop-topaligned.png`, and `final-stage-find-mobile.png`. The desktop hero places the search panel and illustration in two broad side-by-side columns (about 557 px and 738 px); mobile stacks the search panel before the full-width artwork. English 390 and Telugu 320 have `scrollWidth === clientWidth` (375 and 305 px respectively); the 16 px inputs remain visible and readable. All five journey stages render once, each with one information panel and one sibling scene; all 48 IDs are unique, every feature belongs to a stage, and the old decorative spine selectors are absent (0 matches). The Agree illustration was recaptured after its top alignment fix; it begins 61 px below the stage top, alongside the 56 px information-column inset. The journey diagram still contains its own route line inside its feature card.

The header seat mark is visible at 40 px desktop, 34 px mobile, and 25 px Telugu 320 px. High-resolution component captures show the car and motorbike silhouettes with the wider, reclined seat: `final-logo-desktop-2x.png`, `final-logo-car-desktop-1x.png`, and `final-logo-bike-desktop-1x.png`. All external SVG symbols render with nonzero bounds. Browser samples showed car opacity decreasing from 1 to 0 while motorbike opacity increased from 0 to 1; the seat kept identical `[156.75, 69, 152.54, 153]` bounds and `transform: none` throughout. Pause held the car state unchanged for 700 ms; reduced-motion mode loaded paused on the car in both EN and TE. Empty search shows the route-required error and focuses pickup. Kondapur → Airport redirects to app login; the app captures both exact text labels and clears the one-time hash. No point coordinates are invented. The isolated browser reported zero page errors.

The final strict public export was refreshed with eight EN/TE pages and 16 allowlisted static dependencies. Manifest SHA256: `3ff6ae30c91d589ba6849dc996fa0e1065d3474eae82b46be191dc9495810ddd`. The existing tunnel returned HTTP 200 for both landing languages and the current landing CSS/JS/brand assets, with matching manifest hashes and `Cache-Control: no-store`. `/static/app.js`, `/api/bootstrap`, and unsupported query strings returned 404. The exported landing has `data-public-static-preview="true"`, the neutral Hyderabad art, and no active combined people/seat-pair art. No new tunnel or deployment was created.

The local root routing was also checked in a clean browser context: hashless EN/TE routes redirect to their matching welcome page; `/?app=1`, `#/login`, and a deep app hash stay on the app root. After Railway deployment `84e7b8e8-e124-4564-9176-6fc65562b929` reported success, fresh real-browser navigation confirmed both production domains (`seatpal.in` and `seatpal.co.in`) route `/?lang=en|te` to localized welcome pages while explicit `#/login` stays in the app. The installed-PWA display-mode bypass was covered by the route worker's tests, not browser emulation.

### Seat-to-SeatPal logo story QA — 14 October 2026

This supersedes the infinite car/motorbike crossfade documented above. The hero mark now plays one 6.6-second sequence: a fitted automotive seat appears in the car, the car gives way to a motorcycle with a proportionate pillion saddle, then both vehicles clear for the final SeatPal mark and wordmark. The detached blue headrest and white seat geometry carry through to the final dark tile. The header/footer mark remains static. Pause/resume preserves the current timeline; completion offers Replay. With JavaScript disabled the final mark is shown directly, and reduced-motion settles on the same static mark without a control.

The public landing snapshot at `http://127.0.0.1:5481/welcome/latest?lang=en` was inspected in the in-app browser at EN 1280 px, EN 390 px and TE 320 px, including paused car, paused bike and settled final states. At desktop scale the fitted seat measured 25.5×34.88 px within the 216.35×85.96 px car; the motorcycle showed its separate fitted pillion saddle. EN390 and TE320 had no horizontal overflow (`scrollWidth=clientWidth`: 375 and 305 px). Browser error and warning logs were empty. Real replay was run twice after waiting seven seconds; both runs settled to `finished`. The controller also passed a Node built-in `vm` behavior harness for initial playback, pause/resume, completion, two replays, initial/live reduced-motion changes, and no automatic restart when reduced motion is disabled.

`tests/test_public_site_latest.py` reported 10 passed and `pytest.main` returned 0; its wrapper process separately reported exit 1 during interpreter teardown, so that teardown status is not represented as a clean process exit. JavaScript syntax, SVG XML parsing, and `git diff --check` passed. Real OS reduced-motion emulation and a browser with JavaScript disabled were not exercised. These checks cover the public landing preview, not the full application, native clients, or production. A self-contained HTML snapshot is saved in the current task outputs at `outputs/seatpal-logo-animation/seatpal-logo-animation-preview.html`.
