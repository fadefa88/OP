# OP Reader

Reader statico/serverless per capitoli organizzati per volume, con frontend su Cloudflare Workers e immagini su Cloudflare R2.

## Architettura

```text
GitHub repo
├── codice sito
├── Worker
├── workflow GitHub Actions
└── manifest JSON diviso per volumi

Cloudflare R2
└── immagini WebP

manga.lucahome.uk
└── sito reader

static.lucahome.uk
└── immagini pubbliche da R2
```

Le immagini non devono essere committate nel repository. Il workflow committa solo JSON sotto `public/content`.

## Manifest

Manifest principale:

```text
public/content/index.json
```

Manifest per volume:

```text
public/content/volumes/001.json
public/content/volumes/002.json
...
public/content/volumes/117.json
```

`public/content/manifest.json` resta solo come file di compatibilità generato automaticamente.

## Dipendenze Python

Da Windows PowerShell, dentro la cartella del repo:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Variabili locali per import storico

In PowerShell, imposta le variabili così:

```powershell
$env:AUTHORIZED_MANGA_BASE_URL="https://tua-sorgente-autorizzata"
$env:I_CONFIRM_RIGHTS="true"
$env:CLOUDFLARE_ACCOUNT_ID="tuo_account_id"
$env:R2_BUCKET_NAME="op-reader-images"
$env:R2_PUBLIC_BASE_URL="https://static.lucahome.uk"
$env:R2_ACCESS_KEY_ID="tua_access_key_id_r2"
$env:R2_SECRET_ACCESS_KEY="tua_secret_access_key_r2"
```

Usa solo una sorgente che puoi copiare e pubblicare legalmente.

## Import storico one-time verso R2

Comando consigliato per importare tutti i capitoli storici fino al 1184:

```powershell
python scripts/import_history_to_r2.py `
  --from-chapter 1 `
  --to-chapter 1184 `
  --extensions jpg,jpeg `
  --max-pages 45 `
  --min-pages 3 `
  --webp-quality 90 `
  --i-confirm-rights
```

Se vuoi importare fino al 1185:

```powershell
python scripts/import_history_to_r2.py `
  --from-chapter 1 `
  --to-chapter 1185 `
  --extensions jpg,jpeg `
  --max-pages 45 `
  --min-pages 3 `
  --webp-quality 90 `
  --i-confirm-rights
```

Lo script:

```text
1. scarica temporaneamente JPG/JPEG dalla sorgente autorizzata
2. converte in WebP qualità 90 mantenendo la stessa risoluzione
3. carica su R2
4. aggiorna solo i manifest JSON
5. non salva immagini nel repository
```

Se si interrompe, rilancialo: i capitoli già presenti nel manifest vengono saltati. Per forzare la riscrittura usa `--overwrite`.

## Import di un solo volume o capitolo

Un volume:

```powershell
python scripts/import_history_to_r2.py `
  --volume 116 `
  --extensions jpg,jpeg `
  --webp-quality 90 `
  --i-confirm-rights
```

Un capitolo:

```powershell
python scripts/import_history_to_r2.py `
  --chapter 1176 `
  --extensions jpg,jpeg `
  --webp-quality 90 `
  --i-confirm-rights
```

## Pattern sorgente

Di default lo script prova URL così:

```text
{base_url}/volumi/volume{volume_padded}/{chapter_padded}/{page_padded}.{extension}
```

Esempio:

```text
https://sorgente/volumi/volume116/1176/01.jpg
```

Se la tua sorgente usa un pattern diverso, passa `--source-template`:

```powershell
python scripts/import_history_to_r2.py `
  --from-chapter 1 `
  --to-chapter 10 `
  --source-template "{base_url}/v{volume_padded}/c{chapter_padded}/{page_padded}.{extension}" `
  --i-confirm-rights
```

Placeholder disponibili:

```text
{base_url}
{volume}
{volume_padded}
{chapter}
{chapter_padded}
{chapter_4}
{page}
{page_padded}
{page_3}
{extension}
```

## Dopo l'import storico

Controlla cosa è cambiato:

```powershell
git status
```

Devono risultare modifiche solo in:

```text
public/content/index.json
public/content/manifest.json
public/content/volumes/*.json
reports/history-import-summary.json
```

Aggiungi solo i manifest:

```powershell
git add public/content/index.json public/content/manifest.json public/content/volumes/*.json
git commit -m "Import historical manga manifests to R2"
git push
```

Non fare `git add .` se hai cartelle temporanee o report che non vuoi versionare.

## Workflow orario nuovi capitoli

File:

```text
.github/workflows/daily-download.yml
```

Ogni ora:

```text
1. legge latestChapter da public/content/index.json
2. prova latestChapter + 1
3. eventualmente prova anche i successivi in scan-ahead
4. calcola il volume in automatico
5. scarica dalla sorgente autorizzata
6. converte in WebP qualità 90
7. carica su R2
8. aggiorna solo JSON
9. fa commit solo se i JSON sono cambiati
```

Il deploy Cloudflare parte solo perché cambia il repository. Se non trova un nuovo capitolo, non committa nulla e quindi non parte deploy inutile.

## Variabili GitHub Actions

Repository → Settings → Secrets and variables → Actions.

Secrets:

```text
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

Variables:

```text
AUTHORIZED_MANGA_BASE_URL
I_CONFIRM_RIGHTS=true
R2_BUCKET_NAME=op-reader-images
R2_PUBLIC_BASE_URL=https://static.lucahome.uk
```

Opzionale, solo se la sorgente usa URL diversi dal default:

```text
AUTHORIZED_MANGA_SOURCE_TEMPLATE
```

## Mappa capitoli/volumi futura

La mappa è dinamica da volume 117:

```text
Volume 117 = 1186-1195
Volume 118 = 1196-1205
Volume 119 = 1206-1215
...
```

Questa regola è implementata in:

```text
scripts/op_importer_common.py
```

## Reader

Il reader legge il manifest assemblato da:

```text
/api/manifest
```

Il Worker combina automaticamente `index.json` e i manifest dei volumi. Le immagini vengono lette dal dominio pubblico R2, per esempio:

```text
https://static.lucahome.uk/op/vol-116/chapter-1176/page-001.webp
```

## Manual single-chapter import from GitHub Actions

Use this when you want to test or import one chapter without running the historical importer from your PC.

Required GitHub configuration:

Secrets:

```text
CLOUDFLARE_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

Variables:

```text
AUTHORIZED_MANGA_BASE_URL
I_CONFIRM_RIGHTS=true
R2_BUCKET_NAME=op-reader-images
R2_PUBLIC_BASE_URL=https://static.lucahome.uk
```

Run:

```text
Actions → Manual Import Single Chapter to R2 → Run workflow
```

Inputs:

```text
chapter: 1176
max_pages: 45
min_pages: 3
webp_quality: 90
overwrite: false
```

The workflow uploads images to R2 and commits only JSON manifest files under `public/content`. It never commits image binaries.
