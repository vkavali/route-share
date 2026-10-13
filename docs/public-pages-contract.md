# Public landing and FAQs

## Audience and job

Adults considering an existing private planned car trip between Hyderabad and Mahabubnagar can understand the service before signing in. The pages replace guessing from the app’s forms: they explain how a seat request becomes accepted, what payment records mean, and what information is shared. Repeat value is a clear, searchable reference with current capability notices. This slice does not add customer transactions.

## Behavior

- Anonymous GET `/welcome` explains the journey; GET `/faq` renders all categories and answers as native HTML disclosures. Neither route creates an authentication session or calls SMS, maps, payments or speech providers.
- `lang=en|te` is case-normalized. Unsupported, missing or malformed values select English. Language links preserve the current public page. App, policy and public-page links preserve language. Existing policies remain English and are labelled as such.
- Open-app links enter the existing app login. The root SPA and authentication flows remain unchanged.
- FAQs can be opened and linked without JavaScript. Optional browser search filters existing answers and supports clearing the query; empty results explain how to recover. A slow or unavailable script does not remove the answers.
- Registration copy reflects the instantiated phone service’s enabled state. Payment copy reflects the payment service’s enabled state and explicitly preserves account eligibility and manual receipt/refund limitations. Neither an enabled flag nor a link promises a successful provider transaction.
- Missing public support configuration produces an honest unavailable message. Only validated configured support email is linked. App name and all content are escaped by the template; content is plain text, never trusted HTML.
- Document review is not a safety guarantee, identity guarantee, government or police clearance. Public guidance does not make tax or legal claims. Optional voice requires availability and user review; foreground location is opt-in and participant-limited. Deletion and optional recovery copy reflect the lifecycle’s retained-record and proof limitations.

## Configuration and boundaries

`APP_DISPLAY_NAME` defaults to SeatPal. Operator/support configuration and existing runtime service gates are reused. No account, booking, payment, SMS, location, or model mutation is introduced. The landing page’s landscape is decorative artwork, not route geometry. Terms/privacy remain the existing policy pages.

Backend checks cover anonymous rendering without cookies, both languages, current enabled/disabled services, malformed inputs and escaped branding, policy links, native FAQ content and unchanged root SPA. Browser QA separately checks responsive layout, search, reset, links and no-JavaScript access. Passing local checks does not establish real SMS/provider activation or production availability.
