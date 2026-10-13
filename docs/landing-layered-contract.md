# Scroll linked feature journey

## Job

An adult considering a Hyderabad–Mahabubnagar journey wants to understand sharing an already planned private car trip before opening the beta. The landing explains the real app features and their limits, with a clear path into the app and detailed answers available without an account. Ride sharing remains the subject; local artwork is a small brand accent.

## Behavior

A single vertical line connects nine visible feature stops. Normal scrolling moves a progress marker forward or backward through the explanation. Progress represents the visitor’s position on the page, not completed tasks, a booking, a vehicle or live GPS. There is no idle road or car animation, scroll hijacking, forced snapping or automatic navigation.

The feature directory uses ordinary links to each stop. Direct links, keyboard navigation, back navigation and upward scrolling work normally. Every stop remains readable without JavaScript; reduced motion uses a static presentation without interpolated travel. Progress must not produce repetitive screen-reader announcements or obscure headings and click targets.

Each stop explains a real feature and links to an existing language-preserving FAQ section. These links do not perform a transaction or create account state. The separate app entry opens the existing sign-in flow. No sample riders, prices, availability or completed actions are presented as real.

## Feature inventory

The canonical English and Telugu content is `copy.journey`: `eyebrow`, `title`, `body`, `progress_label` and `stops`. Each stop has a stable `id`, `title`, `body`, up to two short `details`, `link_label` and a context-generated `href`. Costs and account stops also receive a runtime `status`. FAQ fragments are fixed and allowlisted; no user-provided or external destinations are accepted.

| Stop | Explanation and important limit | FAQ section |
| --- | --- | --- |
| plan | Pickup, drop-off, time and compatible routes; search is not a reservation. Voice is being tested in the native app; web visitors type their places. | location-voice |
| offer | Seats on an already planned private journey; offering requires current document approval. | getting-started |
| driver | Owner profile, vehicle, current document-review status and eligible ratings; review is not police clearance or a safety guarantee. | trust |
| request | Meeting points, pending request, owner acceptance, trip status and available cancellation actions. | requests |
| chat | Chat in an accepted booking to confirm pickup details and coordinate changed plans. | requests |
| live | Optional foreground sharing with accepted-trip participants; stop, screen exit and expiry end sharing, and updates can fail. | location-voice |
| costs | Declared costs and owner share, contribution agreement and manual payment records; opening UPI does not verify settlement. | contributions |
| reviews | Completed-trip ratings with public-comment consent, reporting and blocking; no emergency response or automatic financial resolution. | trust |
| account | Actual signup availability, optional saved-code recovery and eligible deletion with limited retained records. | account |

Signup and UPI notices use the existing instantiated capability flags. Disabled services remain explicitly unavailable; the explanation does not activate them. Existing pilot coverage, account permissions, privacy behavior, FAQ content and working app actions remain unchanged.

## Presentation

Use one consistent vertical rhythm, crisp typography, restrained surfaces and a clearly subordinate progress line. Preserve ivory, forest, sage and lime, with live Manrope and Anek Telugu text. Small local miniatures may support the explanation without becoming destinations. The previous photographic tourism layout, painted road transitions and travelling-car treatment are superseded.

Reserve space for the line and marker so neither covers text or controls. Recalculate scroll geometry after fonts load, content changes and viewport resizing; safe static content remains available before measurements are ready. Mobile layouts must keep headings, explanations and actions legible at 320px, without horizontal scrolling or mandatory animation.

## Verification

Review English and Telugu at 320, 390, 768 and 1440px. Scroll down and back up, jump to each stop, open a direct stop link, use keyboard and browser back, and check every FAQ destination. Verify progress follows the visible content without marking app tasks complete. Check font loading, resize, reduced motion, JavaScript disabled and failed artwork; content and actions remain usable.

Confirm runtime disabled signup and UPI notices remain accurate, all nine stops are visible and no navigation or authentication behavior changes. Run focused public HTTP checks after the coordinated template and copy changes. No provider activation, Git commit or deployment is implied by this design correction.
