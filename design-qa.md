# Route Share reference UI correction — 6 October 2026

## Result and scope

Component/layout visual review: passed. The former small-map / white-bottom-sheet composition is replaced by the selected reference's ivory page, heading, separate white route cards, horizontal date area, large map, and forest/lime actions. Login uses the selected illustration followed by working white-sheet controls.

**This is not an exact image match.** The generated reference's illustrated cartography is materially different from the existing factual OpenStreetMap raster basemap. No new map provider was enabled. Labels, land shapes, road density, and coastline color consequently differ. This is a documented functional-map constraint, not a claim of pixel fidelity. The existing leaf brand asset also differs from the reference's road/leaf mark. Full illustrated-map fidelity remains outside this release's verified result.

## Source and comparison evidence

- Forms source: `C:/Users/vkava/Downloads/hf_20261006_171345_c4fea31e-71c5-4fbe-8b78-c8403011d052.png`, 2160 × 3840.
- Login source: `C:/Users/vkava/Downloads/hf_20261006_171443_34f3a932-fc5c-4dc7-9a09-b5ca2b3733fe.png`, 2160 × 3840.
- Actual screenshots: `outputs/reference-rebuild/drive-form-en-390.png`, `drive-form-te-390.png`, `search-form-en-390.png`, `search-form-te-390.png`, `login-en-390.png`, and `drive-en-1280.png`.
- Full-view equal-width comparison: `outputs/reference-rebuild/forms-comparison.png` and `login-comparison.png`.
- Focused route/date comparison: `outputs/reference-rebuild/forms-controls-comparison.png`.
- Real populated route: `outputs/reference-rebuild/drive-preview-en-390.png`.
- Mobile CSS viewport: 390 × 844, device scale factor 1. Desktop: 1280 × 900, scale factor 1. Full-page captures include scrollable content. References normalized to 390 × 693; comparisons align the page top at equal density. Source contains populated example cities and a synthetic illustrated route; empty-account screenshots deliberately contain no invented cities. Populated route evidence uses actual selected cities and returned OSRM geometry. Driver capacity/detour and passenger pickup window are production requirements absent from the source image, so those screens are taller.

## Required fidelity surfaces

- Typography: bundled Manrope, 800-weight heading and 650-weight route values; bundled Anek Telugu with natural Telugu line height. No fallback font or clipped Telugu labels observed. Native date fields were widened after initial clipping was found.
- Spacing/layout: 16px mobile gutters, separate stop cards, one date panel, 358 × 293px map at 390px, broad action pair. Desktop places the large live map beside the fields. No bottom-sheet overlap or enclosing white form card remains.
- Colors: ivory `#f6f5f0`, forest actions `#173e35`, lime secondary action `#d8ed83`, white controls and muted sage labels. The live basemap is quieter but not the illustrated source palette.
- Image quality: original selected login artwork is cropped only to its illustration region; no image covers the working account/password controls. Current Phosphor library icons and existing brand assets remain. No new generated assets or external provider were introduced.
- Copy/content: English and Telugu form headings, date timezone, capacity, detour, and action labels checked. Password remains required and enabled. Private beta caveats remain visible. Empty locations are honest prompts, not the source's sample cities.

## Comparison history and fixes

1. P1: map-first bottom sheet had the wrong region order and proportions. Replaced both form renderers with a dedicated reference composition and new scoped stylesheet.
2. P2: inherited separator, uppercase labels, and tiny final marker conflicted with the new stop cards. Reset inherited rules; retained the connected route rail and real picker buttons.
3. P2: driver timezone dropped to a second row because an empty validation element occupied a grid cell. Hid empty validation notes; retained full-width visible errors.
4. P2: Telugu native datetime values clipped when both windows were side by side. Rebuilt the window panel as two horizontal rows with full readable date/time values.
5. P2: login account label overflow and excessive boxed-card treatment. Shortened English Administrator to Admin; rebuilt controls on a full-width white sheet and ensured image decoding before capture.
6. QA fixture issue: the prior isolated database contained an incomplete synthetic trip, causing an unrelated `/api/state` 500. Preserved it and used fresh `work/reference-ui-20261006.sqlite3`; real local and production data were untouched.

## Browser validation

- Existing form suite: 33 checks passed, 7 screenshots, zero page errors, zero non-login POSTs. Covers required/wrong/right passwords, real map picks, browser back, preserved drafts, date validation, one passenger seat, driver 1–6 seat boundaries, detour values, English/Telugu and mobile/desktop layout.
- Passenger flow: real Hyderabad/Vijayawada search submitted twice, both HTTP 200 with zero matches in the empty test account; `outputs/reference-rebuild/search-flow.json`.
- Real driver flow: Hyderabad and Vijayawada selected through live geocoding, preview submitted twice, both HTTP 200; OSRM returned 3,689 coordinates each time. Nothing published. Evidence: `outputs/reference-rebuild/live-flow.json`.
- Source reference and actual screenshots inspected together, including the focused route/date region. Automated overflow checks alone were not treated as a visual pass.
- Known limits: live cartography differs from illustration; no TestFlight/signing work was performed; this review does not revalidate every unrelated product screen or claim production identity verification.

## Implementation checklist

- [x] Real form composition rebuilt around the selected reference.
- [x] Password and existing action/data hooks preserved.
- [x] Mobile English/Telugu and desktop inspected.
- [x] Existing behavioral checks and repeated real route preview passed.
- [x] Runtime-only deployment bundle excludes credentials and databases.
- [x] Railway deployment `0218dacf-159b-41f6-bb9e-575dc4b44e9c` reached SUCCESS with one running replica. Live smoke: 26 checks, zero page errors, zero non-login writes; all 9 source/deployed hashes match. Deployed English/Telugu forms, sign-in, and desktop capture inspected in `outputs/live-reference-rebuild/`.
- [x] Delayed bootstrap, two independent tab drafts, and EN/TE 320/768/1280px layout checks passed (`outputs/reference-rebuild/resilience.json`).

final result: passed

## Safety typography correction — 2026-10-06

User clarified that the complaint was rough, dated-looking typography and controls, not map-network failures. Compared the supplied safety screenshot with selected green/ivory safety reference `hf_20261006_171443_eae9a6c7-4aaa-415f-ab7c-9fc0791b896f.png`.

Chrome verified the existing custom Manrope font actually rendered (SemiBold before, ExtraBold after), viewport scale 1, DPR 1, no heading transform. This was not a missing-font diagnosis. The old form used 13px choice text, 12px field labels, 400 body weight from a late override, and low-contrast secondary text. Shared body weight is now 500, secondary text is darker, and navigation is 14px/600. Safety uses 38px/800 desktop and 30px/800 mobile headings, 16px desktop and 14px mobile category text, 18px/17px section labels, larger vector icons, white rounded sheet and subtle depth. Controls, required detail validation, block confirmation and emergency link semantics are preserved. No map provider or 3D feature was introduced.

Validation against isolated local accepted-booking fixture on port5002: English 320px, 390px DPR1/DPR2, 1435px, and Telugu 390px DPR2; no horizontal overflow or browser exceptions. Radio selection works, empty and five-character details remain invalid, cancelling block confirmation preserves entered details, and a second tab opens with its own empty draft. Repeated full run passed after one earlier second-tab timing timeout. No report or block was submitted. Safety backend tests: 4 passed. Shared home also checked for overflow at 320/390/1435. Captures inspected: `outputs/type-before-desktop.png`, `outputs/type-after-desktop.png`, `outputs/type-after-en-390-dpr2.png`, `outputs/type-after-te-390-dpr2.png`; detailed browser results in `work/type-validation.json` (local evidence, not deployment proof).

Limitations: this verifies rendered browser styles on the local fixture, not subjective acceptance, OS-level text rasterization on every display, full reference fidelity, or a native device. Existing OSM map artwork remains different from the illustrated reference. Deployment and signed native build are coordinated separately.
