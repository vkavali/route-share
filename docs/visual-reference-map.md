# Route Share visual reference map

The supplied screenshots guide the layout. The sign-in source is also used unmodified as decorative hero art, cropped to its illustrated upper region; the remaining screenshots stay in Downloads. Production forms keep their real controls and live map canvas. Screenshot map illustrations are never used as route data or as a substitute for a live map.

| Flow | Source screenshot | Runtime asset / implementation |
| --- | --- | --- |
| Sign in | `hf_20261006_171443_34f3a932-fc5c-4dc7-9a09-b5ca2b3733fe.png` | `/static/assets/higgsfield-signin-reference.png` is the exact unmodified reference, clipped to the upper artwork region; working account choice, password, visibility toggle, and sign-in remain HTML controls below it. |
| Home | `hf_20261006_171532_6272c8cd-e4e4-4112-aa4a-a63fe44b9f35.png` | Live `#journey-map` map canvas, live origin/destination picker buttons, swap and search/offer actions; `/static/assets/journey-landscape.webp` for the bottom landscape. |
| Search form | `hf_20261006_171345_c4fea31e-71c5-4fbe-8b78-c8403011d052.png` | Live `#journey-map`; functional route-point, pickup-window, seat-count, and search controls. Map tiles and route lines come from the actual configured map/route data. |
| Point picker | `hf_20261006_171345_29be2ad7-4b57-4b6c-9904-2a3d54dcb4f3.png` | Existing interactive Leaflet picker, `/api/places` manual search, selected-point sheet, map pin, and location button. The generated reference map is not shown as a substitute for the real map. |

Typography uses the locally bundled Manrope and Anek Telugu variable fonts. Icons come from the application's Phosphor icon set. No reference screenshot or fixed route is embedded into a live map view.
