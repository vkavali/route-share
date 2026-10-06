import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const vendor = resolve(root, 'static/vendor/leaflet');
const js = await readFile(resolve(vendor, 'leaflet.js'), 'utf8');
let css = await readFile(resolve(vendor, 'leaflet.css'), 'utf8');
if (!js.includes('Leaflet 1.9.4')) throw new Error('Expected vendored Leaflet 1.9.4.');

for (const name of ['marker-icon.png', 'marker-icon-2x.png', 'marker-shadow.png', 'layers.png', 'layers-2x.png']) {
  const bytes = await readFile(resolve(vendor, 'images', name));
  const mime = 'image/png';
  const uri = `data:${mime};base64,${bytes.toString('base64')}`;
  css = css.replaceAll(`url(${`images/${name}`})`, `url(${uri})`)
    .replaceAll(`url('${`images/${name}`}')`, `url('${uri}')`)
    .replaceAll(`url("${`images/${name}`}")`, `url("${uri}")`);
}
if (/url\(['"]?images\//.test(css)) throw new Error('Leaflet CSS still references unbundled images.');

const digest = value => createHash('sha256').update(value).digest('hex');
const output = resolve(here, '../src/generated/leaflet.ts');
const contents = `// Generated from ../static/vendor/leaflet/Leaflet 1.9.4. Do not edit.\nexport const LEAFLET_VERSION = '1.9.4';\nexport const LEAFLET_JS_SHA256 = '${digest(js)}';\nexport const LEAFLET_CSS_SHA256 = '${digest(css)}';\nexport const LEAFLET_JS = ${JSON.stringify(js)};\nexport const LEAFLET_CSS = ${JSON.stringify(css)};\n`;
await writeFile(output, contents);
console.log(`Generated local Leaflet WebView source (${Buffer.byteLength(contents)} bytes).`);
