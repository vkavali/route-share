# SeatPal mobility redesign preview

## Job and behavior
SeatPal serves people sharing seats on trips they already planned. A passenger needs to get somewhere; a driver has room on a compatible trip. The repeated-use requirement is accurate route selection and a clear booking outcome. Existing identity, authentication, matching, payment and availability rules stay authoritative.

A visitor can enter the app, read the five-stage journey, change language, replay the approved seat/car/bike identity, explore examples, search FAQs and open policies/support. The app keeps its real sign-in, recovery, location picker, route search, booking, profile and support actions. Empty, pending, invalid and unavailable states remain explicit. No fabricated drivers, ratings, live positions, fares, reviews or metrics are introduced.

## Reference review and correction
The first visual pass mostly changed palette and spacing; the user rejected it while viewing login. It is preserved at `output/design-snapshots/clean-pass-20261014/` as source files, not a Git commit. The next revision changes composition and action hierarchy.

Official public sites were inspected in a real browser at 1440x1000 and 390x844 on 2026-10-14:
- Rapido: pickup and destination lead directly to the booking action; transport imagery makes the category explicit. https://rapido.bike/Home?lan=en
- Uber: destination controls and the next price/request decision dominate; the mobile layout removes the desktop image collage. https://www.uber.com/in/en/ and https://www.uber.com/us/en/ride/how-it-works/
- Lyft: human-scale campaign photography with a clear rider/driver distinction and one strong action. https://www.lyft.com/
- Waymo: clear ride entry, service availability and a sequential pickup experience. https://waymo.com/rides/
- Apple: dominant product composition, restrained navigation, paced chapters and purposeful media controls. https://www.apple.com/apple-watch-ultra-4/

These are public-site and documented-flow observations, not a claim to have tested those companies' native apps. The Uber browser resolved to a US location despite the India URL. Competitor images, branding, copy, promotions and service claims are not reused.

## Current composition
- Login: one focused form column, without a landscape banner or nested marketing cards. In private beta, the usable existing password form is visible first; phone unavailability, retry and recovery remain accessible below. When phone registration is enabled, its real form remains primary and staff sign-in secondary. Passwords and permissions are unchanged.
- Home/search: a purposeful route form beside a large real map on desktop; map context followed by the route sheet on mobile. Existing controls, search validation and booking transitions are preserved.
- Landing: white canvas, strong left-aligned typography, direct Find a seat and Offer a seat actions, and an original editorial image. The five-stage vertical journey remains. The approved animated identity stays a compact brand detail instead of occupying the entire opening.
- Shared system: neutral nearblack text, white surfaces, forest action color and restrained lime selection accents; 14px controls, 24px principal surfaces, comfortable touch targets, visible focus and reduced-motion support. English uses the platform font; Telugu uses Anek Telugu with script-appropriate leading.

The hero image is AI-generated illustrative promotional art, not a photograph of actual customers, a coverage claim, or evidence that motorbike rides are available. Its adjacent provenance record preserves that distinction. No fake route line is used: repository corridor metadata is not road geometry.

## Working behavior and boundaries
The map now observes container resize, updates Leaflet's cached size and disconnects on disposal. This resolves incomplete tile coverage after layout changes without changing the route or provider. The map's OpenStreetMap attribution stays visible.

No commit, push, deployment, TestFlight upload, new auth provider or public-signup activation is included in this preview. Existing backend/email work is preserved. This visual work does not establish production readiness. Native typography/theme groundwork has type and harness checks; actual iPhone/Android rendering and frame-rate performance still need device verification.

## Verification scope
Review the final browser evidence in the task workspace under `output/playwright/mobility-revision/`; reference captures are under `output/playwright/mobility-reference/`. Test actual local demo sign-in, route-picker and invalid search behavior, profile persistence, EN/TE, 320px/390px/desktop, keyboard FAQ use and reduced motion. Public template tests, native type checks and existing auth/map lifecycle harnesses supplement browser checks. Synthetic provider tests must be described separately from real basemap captures.
