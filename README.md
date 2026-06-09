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
└── immagini ottimizzate: WebP quando è più leggero, altrimenti JPG originale

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
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Uso il Python del virtual environment direttamente, così non serve abilitare `Activate.ps1` nelle policy di PowerShell.

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

## Import massivo one-time verso R2

Per caricare tutto l'archivio storico usa il nuovo script:

```text
scripts/import_all_to_r2.py
```

Comando consigliato da PowerShell, dentro la cartella del repo:

```powershell
.\.venv\Scripts\python.exe scripts\import_all_to_r2.py `
  --from-chapter 1 `
  --to-chapter 1185 `
  --extensions jpg,jpeg `
  --max-pages 45 `
  --min-pages 3 `
  --webp-quality 82 `
  --image-strategy best-size `
  --pause-every 50 `
  --pause-seconds 20 `
  --i-confirm-rights
```

Logica dell'import massivo:

```text
1. parte dal capitolo 1
2. per ogni capitolo calcola automaticamente il volume corretto
3. prova le pagine JPG/JPEG una alla volta
4. quando trova immagini valide, le converte in WebP qualità 82 mantenendo la stessa risoluzione
5. usa WebP solo se pesa meno del JPG/JPEG originale
6. se WebP pesa di più, carica su R2 il JPG originale
7. aggiorna solo i manifest JSON divisi per volume
8. non salva mai immagini nel repository
9. scrive un checkpoint dopo ogni capitolo
10. se si interrompe, puoi ripartire senza rifare tutto
```

La mappa volumi/capitoli è questa:

```text
Volumi 1-116: tabella storica dentro scripts/op_importer_common.py
Volume 117: capitoli 1186-1195
Volume 118: capitoli 1196-1205
Volume 119: capitoli 1206-1215
Poi ogni volume aumenta di 10 capitoli indefinitamente.
```

Se lo script si interrompe, rilancia così:

```powershell
.\.venv\Scripts\python.exe scripts\import_all_to_r2.py `
  --from-chapter 1 `
  --to-chapter 1185 `
  --resume-from-checkpoint `
  --extensions jpg,jpeg `
  --webp-quality 82 `
  --image-strategy best-size `
  --i-confirm-rights
```

I capitoli già presenti nel manifest e presenti su R2 vengono saltati. Per forzare la riscrittura usa `--overwrite`.

Al termine trovi:

```text
reports/import-all-progress.json
reports/import-all-summary.json
```

## Import di un solo volume o capitolo

Un volume:

```powershell
python scripts/import_history_to_r2.py `
  --volume 116 `
  --extensions jpg,jpeg `
  --webp-quality 82 `
  --i-confirm-rights
```

Un capitolo:

```powershell
python scripts/import_history_to_r2.py `
  --chapter 1176 `
  --extensions jpg,jpeg `
  --webp-quality 82 `
  --i-confirm-rights
```


## Strategia immagini: best-size

Per default gli importer usano:

```text
image_strategy = best-size
webp_quality = 82
```

La logica è:

```text
1. scarica il JPG/JPEG originale
2. prova conversione WebP alla qualità indicata
3. se WebP pesa meno, carica WebP su R2
4. se WebP pesa di più, tiene il JPG originale
5. il manifest punta automaticamente all'estensione corretta pagina per pagina
```

Strategie disponibili:

```text
best-size = scelta consigliata, WebP solo quando conviene
webp      = forza sempre WebP
original  = carica sempre il file originale
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
6. usa strategia best-size: WebP qualità 82 solo se più leggero, altrimenti JPG originale
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
https://static.lucahome.uk/op/vol-116/chapter-1176/page-001.jpg
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
webp_quality: 82
image_strategy: best-size
overwrite: false
```

The workflow uploads images to R2 using `best-size` by default and commits only JSON manifest files under `public/content`. It never commits image binaries.

## Import massivo da GitHub Actions verso R2

Se la sorgente autorizzata consente accesso solo dagli IP dei runner GitHub, usa il workflow manuale:

```text
Actions → Mass Import Archive to R2 → Run workflow
```

Parametri consigliati per il primo caricamento completo:

```text
from_chapter: 1
to_chapter: 1185
batch_size: 20
max_pages: 45
min_pages: 3
webp_quality: 82
image_strategy: best-size
overwrite: false
stop_on_error: false
pause_seconds_between_batches: 10
```

La logica resta questa:

```text
1. GitHub Actions scarica solo dalla sorgente autorizzata.
2. Ogni capitolo viene convertito pagina per pagina con strategia best-size.
3. Se WebP qualità 82 pesa meno del JPG/JPEG, viene caricato WebP.
4. Se WebP pesa di più, viene mantenuto JPG/JPEG.
5. Le immagini vengono caricate su Cloudflare R2.
6. GitHub committa solo i JSON in public/content.
7. Le immagini non vengono mai committate nel repository.
8. Il workflow committa a batch, così se si interrompe puoi rilanciarlo con lo stesso range.
9. I capitoli già presenti nel manifest e già presenti su R2 vengono saltati.
```

Per rendere il primo import più robusto, il workflow processa il range a blocchi e fa commit dopo ogni blocco. Se il job si interrompe, rilancia lo stesso workflow con gli stessi parametri: lo script salterà i capitoli già importati correttamente.

Durante l'import massivo, il workflow orario e il workflow manuale a capitolo singolo condividono la stessa concurrency group `r2-import-runs`, così non dovrebbero sovrapporsi allo stesso import R2/manifest.
