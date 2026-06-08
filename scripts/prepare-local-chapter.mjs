import { mkdir, readdir, copyFile, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const ROOT = process.cwd();
const MANIFEST_PATH = path.join(ROOT, 'public', 'content', 'manifest.json');
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.avif', '.svg']);

function getArg(name, fallback = null) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1) return fallback;
  return process.argv[index + 1] ?? fallback;
}

function slugify(value) {
  return String(value)
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '') || 'chapter';
}

function naturalSort(a, b) {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

const sourceDir = process.argv[2];
if (!sourceDir) {
  console.error(`Uso:
node scripts/prepare-local-chapter.mjs ./input/capitolo-001 --series my-series --series-title "Mio Manga" --chapter chapter-001 --title "Capitolo 001"`);
  process.exit(1);
}

const seriesId = slugify(getArg('series', 'op'));
const seriesTitle = getArg('series-title', seriesId.replaceAll('-', ' '));
const chapterId = slugify(getArg('chapter', path.basename(sourceDir)));
const chapterTitle = getArg('title', chapterId.replaceAll('-', ' '));
const description = getArg('description', 'Manga importato da file locali autorizzati.');

const absoluteSource = path.resolve(ROOT, sourceDir);
const files = (await readdir(absoluteSource))
  .filter((file) => IMAGE_EXTENSIONS.has(path.extname(file).toLowerCase()))
  .sort(naturalSort);

if (files.length === 0) {
  console.error('Nessuna immagine trovata. Estensioni supportate: jpg, jpeg, png, webp, avif, svg.');
  process.exit(1);
}

const targetDir = path.join(ROOT, 'public', 'manga', seriesId, chapterId);
await mkdir(targetDir, { recursive: true });

const pages = [];
for (const [index, file] of files.entries()) {
  const ext = path.extname(file).toLowerCase();
  const targetName = `page-${String(index + 1).padStart(3, '0')}${ext}`;
  await copyFile(path.join(absoluteSource, file), path.join(targetDir, targetName));
  pages.push({ src: `/manga/${seriesId}/${chapterId}/${targetName}` });
}

const manifest = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'));
manifest.generatedAt = new Date().toISOString();
manifest.series ||= [];

let series = manifest.series.find((item) => item.id === seriesId);
if (!series) {
  series = {
    id: seriesId,
    title: seriesTitle,
    description,
    cover: pages[0].src,
    chapters: []
  };
  manifest.series.push(series);
}

series.title = seriesTitle;
series.description = description;
series.cover ||= pages[0].src;

const chapter = {
  id: chapterId,
  number: Number(getArg('number', series.chapters.length + 1)),
  title: chapterTitle,
  publishedAt: getArg('published-at', new Date().toISOString().slice(0, 10)),
  pages
};

const existingIndex = series.chapters.findIndex((item) => item.id === chapterId);
if (existingIndex >= 0) series.chapters[existingIndex] = chapter;
else series.chapters.push(chapter);

series.chapters.sort((a, b) => (Number(a.number) || 0) - (Number(b.number) || 0));

await writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Import completato: ${series.title} / ${chapter.title} (${pages.length} pagine)`);
