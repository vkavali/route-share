# SeatPal landing: Apple Ultra reference

Reference: https://www.apple.com/apple-watch-ultra-4/

Inspected desktop and mobile hero and highlights screenshots on 14 October 2026. The implementation follows the reference's charcoal compact global nav, centered black opening, two-line product proposition, dominant material product object, blue pill action, dark oversized horizontal highlights, compact sticky subnav and long chapter pacing. It uses SeatPal's actual name, approved logo and truthful product copy; no Apple graphics, product claims, pricing or navigation are copied.

The premium device shows an actual locally captured app preview. Its caption states that no route or ride availability is selected. The screen is the current fixture-authenticated passenger home with real OSM tiles and empty pickup/destination controls. Existing beta registration/payment gates and explanatory copy remain driven by the backend context.

Four highlight slides use native horizontal scrolling, scroll snap, previous/next buttons, direct position dots and keyboard arrows/Home/End. They do not autoplay; a pause control is therefore unnecessary. Without JavaScript, the native scroll surface and every slide remain available. Reduced motion removes smooth movement. All hero text renders directly without a reveal or transform.

The complete five-stage vertical journey, feature deep links, pending/accepted and optional-sharing examples, role guide, animated brand replay, FAQ/support/legal links and EN/TE choice remain available. Landing loads isolated landing-ultra.css and landing-ultra.js, avoiding the rejected legacy landing CSS cascade. FAQ and policy keep their existing light presentation.

Rejected local alternatives are saved in output/design-snapshots/clean-pass-20261014 and output/design-snapshots/mobility-rejected-20261014. No commit or deployment is part of this revision.

The device orientation responds subtly to native hero scroll in one animation frame callback; the effect stops with reduced motion or a hidden document. It never moves or hides copy.
