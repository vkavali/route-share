# Festival greetings slice

This slice implements in-app delivery only: SeatPal shows one quiet, dismissible greeting on the latest public landing page and on an authenticated user's app home. The component is not mounted on route-entry forms, booking or payment flows, active trips, or SOS views. If today's India date has no catalog entry, the component returns no markup and leaves no empty gap. Push, SMS, and WhatsApp delivery remain pending a separate review of existing consent, provider, and opt-out behavior.

The date selector uses explicit `Asia/Kolkata` calendar parts. Republic Day (January 26), Independence Day (August 15), Gandhi Jayanti (October 2), Christmas (December 25), and New Year (January 1) are recurring fixed dates. The movable dates in the module are curated for 2026 only. They are not carried into 2027; annual refresh and any moon-sighting updates need manual review.

The selected 2026 calendar is a national baseline, not a claim that every regional calendar uses the same date. State calendars can differ. Sankranti is shown on January 14 from the central calendar; regional observances may vary. On dates when multiple movable holidays overlap, their names are combined in one banner. A fixed national observance has priority 100 and intentionally takes precedence over any other event that day. Good Friday and Muharram use a respectful remembrance message. SeatPal does not infer a person's religion or preferences.

Dismissal is stored by event id and India date in same-origin `localStorage`, so it survives reloads and is shared by tabs on that origin. If browser storage is unavailable, dismissal works for the current page lifetime. The preview must inject a separate storage adapter so simulated dismissals do not affect a live visitor's storage.

## Source metadata

Each movable catalog entry carries its source key and URL for review:

- India Post holiday list: <https://www.indiapost.gov.in/holidays-list>. Used for the national movable dates not specifically sourced to the central calendar below.
- Central Government Holidays list: <https://www.cgca.gov.in/ccaAP/list-of-holiday>. Used for Holi (March 4), Sankranti (January 14), Ugadi (March 19), Onam (August 26), Raksha Bandhan (August 28), Janmashtami (September 4), Maha Shivratri (February 15), and Ganesh Chaturthi (September 14).
- India Post holiday list: <https://www.indiapost.gov.in/holidays-list>. Eid-e-Milad is listed on August 26, the same date as Onam in the selected central calendar; the greeting combines both names.
- Telangana 2026 calendar: <https://www.telangana.gov.in/Downloads/calendar-2026/>. Used for Bathukamma (October 18).

The greeting uses English, Telugu, or Hindi copy selected from the current UI language. An unsupported language safely falls back to English. All event-specific titles are curated; the body remains generic except for the remembrance treatment.
