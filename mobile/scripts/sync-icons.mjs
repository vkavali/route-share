import {readFile, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const workspace = resolve(here, '../../');
const source = await readFile(resolve(workspace, 'static/icons.js'), 'utf8');
const start = source.indexOf('const sourceSvgs = Object.freeze({');
const end = source.indexOf('\n});', start);
if (start < 0 || end < 0) throw new Error('Unable to find shared icon source map');
const block = source.slice(start, end);
const entries = [...block.matchAll(/^\s+(\w+): ("(?:\\.|[^"\\])*")(?:,)?$/gm)];
const wanted = new Set([
  'home','car','steeringWheel','user','users','mapPin','mapTrifold','magnifyingGlass',
  'arrowRight','arrowLeft','arrowsDownUp','plus','minus','eye','eyeSlash','lockKey',
  'star','crosshair','phone','prohibit','warning','chatCircleDots','dotsThree',
  'checkCircle','signOut','list','calendarBlank','path','navigationArrow','stack'
]);
const icons = Object.fromEntries(entries.map(([,name,quoted]) => [name, JSON.parse(quoted)]).filter(([name]) => wanted.has(name)));
if (Object.keys(icons).length !== wanted.size) throw new Error('Shared icon map is missing required names');
const output = `// Generated from static/icons.js. Path data remains verbatim from @phosphor-icons/core 2.1.1.\nconst sources: Record<string, string> = ${JSON.stringify(icons, null, 2)};\n\nexport function appIcon(name: string, {size = 24, color = '#173d32'}: {size?: number; color?: string} = {}) {\n  const source = sources[name];\n  if (!source) return '';\n  const safeSize = Math.max(1, Math.min(256, Math.round(Number.isFinite(size) ? size : 24)));\n  const safeColor = /^#[0-9a-fA-F]{6}$/.test(color) ? color : '#173d32';\n  return source.replace('<svg ', \`<svg width="\${safeSize}" height="\${safeSize}" fill="\${safeColor}" focusable="false" aria-hidden="true" \`).replace(/currentColor/g, safeColor);\n}\n`;
await writeFile(resolve(workspace, 'mobile/src/generated/icons.ts'), output);
console.log(`Synced ${Object.keys(icons).length} shared Phosphor icons.`);
