# Public page polish contract

The public pages help adults considering a shared, already planned Hyderabad–Mahabubnagar journey understand the beta before signing in. A visitor must be able to explain what the app does, distinguish requesting a seat from offering a trip, and see whether signup and payments are available. This pass also polishes the existing web sign-in presentation and startup feedback. Booking, authentication, payment and account rules remain unchanged.

## Visual direction

Keep warm ivory `#f6f5f0`, forest `#173d34`, sage `#52695e`, pale green `#e9eee3` and restrained lime `#d6ea99`. Manrope carries English; Anek Telugu carries Telugu, including language controls. Text remains live HTML with sufficient line height and scalable controls.

The desktop hero has a generous typographic block beside a separate framed Hyderabad landscape. The scene contains no operational map, fabricated route, price, user or metric. On phones, the headline, explanation, action and current beta status precede the scene. The existing leaf-road mark accompanies the configurable product name. Borders and a single restrained scene shadow establish depth; repeated floating cards and text-over-image treatments are excluded.

## Behavior

- Every app action remains a language-preserving link to existing sign-in. Availability comes from server capability checks.
- A Rider or Owner switch changes only the explanatory steps. It uses keyboard-operable tabs with a selected state and a corresponding labelled panel. Without JavaScript, both sequences remain visible and the switch is absent.
- FAQs remain native disclosure elements with all answers server rendered. Search is optional enhancement: normalize text, split the query into words, and require each word to occur somewhere in the question, answer or category. Display the actual match count and a useful empty state. Reset restores questions and the prior disclosure state.
- Desktop category navigation remains visible and indicates the category in view. Selecting a category clears an active filter before navigation. Direct question links reveal the answer. Language changes preserve the page; sign-in links preserve the selected language.
- No account, location permission, API mutation, tracking cookie, new dependency or external font is needed. Reduced-motion preference disables decorative transitions. No action relies on animation.
- Login retains all existing account-selection, password, disclosure, phone-entry and recovery hooks. When public registration is disabled, the existing staff/test-account disclosure is prominent; it does not bypass passwords or create access.
- Initial HTML shows a visible loading state even before scripts arrive. Once the app module loads, the status uses the selected language. Actual bootstrap completion or failure replaces the loading state through the existing rendering and error handling. A public information link remains usable while waiting. No invented progress percentage is shown.

## Acceptance

Inspect landing, FAQs and login in English and Telugu at 320, 390, 768 and 1440 pixels. Check long text, readable contrast, 44-pixel controls, header wrapping, clear scene separation and footer reachability. Exercise role switching by pointer and keyboard, FAQ multiword/category search, empty/reset, hash navigation, language and app links, and no-JavaScript public content. Verify missing support is shown once and capability-disabled states do not invite signup or payment. Check actual local test-account sign-in, password visibility, disclosure state, slow bootstrap and bootstrap failure. No real SMS, banking or native-device behavior is claimed by this web polish.
