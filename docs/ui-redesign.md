# UI Redesign — Dark Mode with Electric Green

Branch: `claude/ui-redesign`

## Design Direction

| Token | Before | After |
|---|---|---|
| Background | `#f6f5f0` (warm off-white) | `#0a0a0f` (near-black) |
| Surface / card | `#fffefa` (pure off-white) | `#141420` (dark blue-grey) |
| Surface muted | `#eef0e6` (light sage) | `#1a1a2a` |
| Primary text | `#173d34` (forest green) | `#f5f5f7` (off-white) |
| Accent / brand | `#173d34` (forest green) | `#00ff88` (electric green) |
| Borders | `#e3e4dc` (light grey-green) | `rgba(255,255,255,0.08)` (hairline) |
| Citron highlight | `#d6ee7a` (lime yellow) | `#00ff88` (electric green) |
| Warning | `#765833` (brown) | `#f0a030` (amber) |
| Danger | `#a0463d` (brick red) | `#ff5050` (vivid red) |

**Typography**: Added `Inter` as the first family preference (uses system install or falls back to Manrope). JetBrains Mono (local source) applied to numeric data: contribution amounts, timestamps, trip detail values.

## Files Changed

| File | What changed |
|---|---|
| `static/styles.css` | `:root` palette, JetBrains Mono `@font-face`, Inter font preference, +240 lines of override rules for hardcoded colors |
| `static/index.html` | `theme-color` → `#0a0a0f` |
| `static/trip-share.html` | `theme-color` → `#0a0a0f` |
| `static/reference-auth.css` | Full rewrite — dark card, green selection state |
| `static/reference-forms.css` | Full rewrite — dark inputs, darkened map filter |
| `static/reference-journeys.css` | Full rewrite — dark `--rj-*` tokens, status chips |
| `static/reference-trip.css` | Full rewrite — dark safety/rating sheets |

## Before / After Notes

### Auth Screen (Sign-in)

**Before**: White card on off-white page. Forest-green brand wordmark. Lime-yellow selected account chip (`#dbef8c`). Forest-green submit button with white text.

**After**: `#141420` card on near-black page. Electric-green brand wordmark. Translucent green selected chip (`rgba(0,255,136,0.12)`) with hairline green border. Electric-green submit button with near-black text (`#0a0a0f`) — high contrast inversion.

### Trip / Journey List

**Before**: White cards with light shadow on warm off-white background. Status chips: lime-yellow (published), yellow-tint (pending), muted green (completed). Contribution amount in standard body font.

**After**: `#141420` cards with dark shadow on `#0a0a0f`. Status chips: translucent green (published/accepted), amber (pending), dim grey (completed), translucent red (cancelled). Contribution amount in JetBrains Mono for instant readability.

### Route Composer (Offer / Search form)

**Before**: White input rows with sage dashed connector. Light-green map background. Dark-green primary action tile. Lime action tile with dark text.

**After**: `#141420` input rows with translucent-green dashed connector. Dark `#0d1117` map pane (+ brightness/saturation filter on tiles). Surface-quiet primary action tile. Electric-green secondary action tile with near-black text.

## Run Command

```
cd route-share
pip install -r requirements.txt
python -m flask --app app run --debug
```

Then open `http://localhost:5000`.

## PR

<https://github.com/vkavali/route-share/pull/new/claude/ui-redesign>
