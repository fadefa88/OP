import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const ROOT = process.cwd();
const PUBLIC_MANGA_DIR = path.join(ROOT, 'public', 'manga');
const bucket = process.env.R2_BUCKET || process.argv[2];

if (!bucket) {
  console.error('Uso: R2_BUCKET=manga-reader-assets npm run upload:r2');
  console.error('Oppure: node scripts/upload-r2.mjs manga-reader-assets');
  process.exit(1);
}

async function walk(dir) {
  const entries = await readdir(dir);
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry);
    const info = await stat(full);
    if (info.isDirectory()) files.push(...await walk(full));
    else files.push(full);
  }
  return files;
}

const files = await walk(PUBLIC_MANGA_DIR);
for (const file of files) {
  const key = path.relative(path.join(ROOT, 'public'), file).replaceAll(path.sep, '/');
  const result = spawnSync('npx', ['wrangler', 'r2', 'object', 'put', `${bucket}/${key}`, '--file', file], {
    stdio: 'inherit',
    shell: process.platform === 'win32'
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

console.log(`Upload R2 completato: ${files.length} oggetti su ${bucket}`);
