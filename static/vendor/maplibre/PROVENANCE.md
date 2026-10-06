# Route Share basemap assets

## Renderer and Leaflet adapter

- `maplibre-gl/dist/maplibre-gl.mjs`, `maplibre-gl-shared.mjs`, `maplibre-gl-worker.mjs`, and `maplibre-gl.css` are MapLibre GL JS **6.11.2**, from the official npm package [`maplibre-gl`](https://www.npmjs.com/package/maplibre-gl). License: 3-Clause BSD, included as `maplibre-gl/LICENSE.txt`.
- `maplibre-gl-leaflet/leaflet-maplibre-gl.js` is the official `@maplibre/maplibre-gl-leaflet` **0.1.4** UMD build. Its declared Leaflet and MapLibre GL JS peer range includes Leaflet 1.9.x and MapLibre GL JS 6.x. License: ISC, included as `maplibre-gl-leaflet/LICENSE`.
- MapLibre is dynamically imported by `static/map-theme.js`; the adapter attaches to the existing Leaflet global. The local worker module is explicitly configured. This keeps Leaflet controls and overlays while using the GL renderer for the basemap.

## Style and data provider

- `static/map-style.json` is based on OpenFreeMap Bright (`https://tiles.openfreemap.org/styles/bright`), fetched 2026-10-06 and adjusted for Route Share's ivory land, sage vegetation, muted roads, blue waterways, and reduced POI clutter.
- Vector, sprite, glyph, and natural-earth data remain served by OpenFreeMap. The style supplies linked attribution to Leaflet: OpenFreeMap, OpenMapTiles, and OpenStreetMap. The rendered control links to `https://openfreemap.org`, `https://openmaptiles.org`, and `https://www.openstreetmap.org/copyright`.
- OpenFreeMap describes its public service as free and suitable for commercial use, requires attribution, and offers no SLA. This prototype therefore does not imply production availability or support guarantees. See [OpenFreeMap](https://openfreemap.org/), its [quick start](https://openfreemap.org/quick_start/), and [terms](https://openfreemap.org/tos/).
- If vector rendering is unavailable or style loading fails, the module uses standard OpenStreetMap raster tiles and their Leaflet attribution. It does not request GPS, geocode, or create markers.

## Telugu font rendering

- `static/map-style.json` uses MapLibre's `font-faces` property for the tile style's `Noto Sans Regular`, `Noto Sans Bold`, and `Noto Sans Italic` stacks, routing Telugu Unicode `U+0C00–U+0C7F` to the locally bundled `static/fonts/AnekTelugu-Variable.woff2`.
- Anek Telugu is SIL Open Font License 1.1; its license and asset provenance are in `static/fonts/OFL-AnekTelugu.txt` and `static/fonts/PROVENANCE.md`.
- The `font-faces` flow was verified in Chrome with MapLibre GL JS 6.11.2: local WOFF2 requests succeeded and Telugu place labels rendered. The map uses translated names only where the vector tile provides the requested language field; this does not guarantee that every place has Telugu coverage.
