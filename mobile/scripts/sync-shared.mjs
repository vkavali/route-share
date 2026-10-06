import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, '../../static/i18n.js');
const generated = resolve(here, '../src/generated/i18n.js');
const hashFile = resolve(here, '../src/generated/i18n.sha256');
const checkOnly = process.argv.includes('--check');
const bytes = await readFile(source);
const hash = createHash('sha256').update(bytes).digest('hex');

if (checkOnly) {
  const current = await readFile(generated);
  const currentHash = createHash('sha256').update(current).digest('hex');
  const recorded = (await readFile(hashFile, 'utf8')).trim();
  if (!bytes.equals(current) || hash !== recorded || currentHash !== recorded) {
    console.error('Native translations are stale. Run `npm run sync:shared` from mobile/.');
    process.exit(1);
  }
  console.log(`Shared translation parity OK (${hash}).`);
} else {
  await mkdir(dirname(generated), { recursive: true });
  await writeFile(generated, bytes);
  await writeFile(hashFile, `${hash}\n`);
  console.log(`Copied shared translations (${hash}).`);
}
