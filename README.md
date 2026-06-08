# OP-main Manga Reader + Cloudflare

Repo unificato tra:

- `OP-main`
- `manga-reader-cloudflare`

Il progetto ora contiene un **manga reader moderno** con:

- frontend statico in `public/`
- Cloudflare Worker in `src/worker.js`
- API `/api/health`, `/api/manifest`, `/api/chapters`
- manifest JSON in `public/content/manifest.json`
- predisposizione Cloudflare R2 per immagini pesanti
- GitHub Actions per deploy Cloudflare
- GitHub Action giornaliera per importare **solo i volumi 115 e 116** da una sorgente autorizzata

> Nota: usa il download reale solo con immagini che puoi legalmente copiare e pubblicare: contenuti tuoi, licenziati, public domain o comunque autorizzati. Il workflow non ha un URL hardcoded verso siti terzi.

---

## Struttura principale

```text
.
├── public/
│   ├── index.html
│   ├── reader.html
│   ├── styles.css
│   ├── app.js
│   ├── reader.js
│   ├── content/manifest.json
│   ├── manga/
│   └── img/                    # asset originali OP-main copiati anche in public
├── src/worker.js
├── scripts/
│   ├── prepare-local-chapter.mjs
│   └── upload-r2.mjs
├── download_manga.py
├── .github/workflows/
│   ├── deploy-cloudflare.yml
│   └── daily-download.yml
├── wrangler.jsonc
├── package.json
└── requirements.txt
```

La cartella `img/` originale è stata mantenuta alla root e copiata anche in `public/img/`, così Cloudflare può servirla come asset statico.

---

## Test locale

Installa dipendenze frontend/Cloudflare:

```bash
npm install
```

Installa dipendenze Python:

```bash
python -m pip install -r requirements.txt
```

Avvia il Worker in locale:

```bash
npm run dev
```

Poi apri l'URL mostrato da Wrangler, di solito:

```text
http://localhost:8787
```

Endpoint utili:

```text
/api/health
/api/manifest
/api/chapters
```

---

## Deploy su Cloudflare

### Secret GitHub necessari

Nel repo GitHub vai in:

```text
Settings → Secrets and variables → Actions → Secrets
```

Aggiungi:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

Ogni push su `main` o `master` esegue:

```text
.github/workflows/deploy-cloudflare.yml
```

Il deploy usa Wrangler e Cloudflare Workers Static Assets.

---

## Import immagini: solo volumi 115 e 116

Il workflow giornaliero è:

```text
.github/workflows/daily-download.yml
```

È limitato a:

```text
volume 115
volume 116
```

Nel file YAML trovi anche il blocco per importare tutto il catalogo, ma è **commentato**.

### Variabili GitHub richieste per attivare il download reale

Vai in:

```text
Settings → Secrets and variables → Actions → Variables
```

Aggiungi:

```text
AUTHORIZED_MANGA_BASE_URL = https://tuo-dominio-autorizzato/esempio
I_CONFIRM_RIGHTS = true
```

Senza queste due variabili il workflow parte, ma salta il download reale.

### Avvio manuale

Da GitHub:

```text
Actions → Import Authorized Manga Volumes 115-116 → Run workflow
```

Puoi anche passare `base_url` manualmente nel form del workflow.

---

## Uso manuale dello script

Audit senza scaricare:

```bash
python download_manga.py \
  --base-url "https://tuo-dominio-autorizzato/esempio" \
  --volume 115 \
  --max-pages 40 \
  --csv reports/audit-volume-115.csv
```

Download reale, solo se hai i diritti:

```bash
python download_manga.py \
  --base-url "https://tuo-dominio-autorizzato/esempio" \
  --volume 115 \
  --max-pages 40 \
  --download \
  --i-confirm-rights \
  --public-dir public \
  --output-dir public/manga \
  --manifest public/content/manifest.json \
  --series-id op \
  --series-title "OP Reader"
```

Per volume 116 cambia solo:

```bash
--volume 116
```

Lo script salva le immagini in:

```text
public/manga/op/chapter-XXXX/page-001.jpg
```

E aggiorna automaticamente:

```text
public/content/manifest.json
```

---

## Import da file locali autorizzati

Puoi evitare download HTTP e importare immagini già in tuo possesso.

Esempio:

```text
input/capitolo-1176/
├── 001.jpg
├── 002.jpg
└── 003.jpg
```

Comando:

```bash
node scripts/prepare-local-chapter.mjs ./input/capitolo-1176 \
  --series op \
  --series-title "OP Reader" \
  --chapter chapter-1176 \
  --number 1176 \
  --title "Volume 116 · Capitolo 1176"
```

---

## Cloudflare R2

Per non appesantire GitHub con migliaia di immagini, puoi usare R2.

In `wrangler.jsonc` è già presente il blocco commentato:

```jsonc
// "r2_buckets": [
//   {
//     "binding": "MANGA_R2",
//     "bucket_name": "manga-reader-assets"
//   }
// ]
```

Dopo aver creato il bucket, lo sblocchi e usi URL nel manifest come:

```json
{ "src": "/api/r2/manga/op/chapter-1176/page-001.jpg" }
```

---

## Note operative

- `daily-download.yml` committa solo se trova nuove immagini o aggiorna il manifest.
- Il push ha retry con `git pull --rebase --autostash` per ridurre i conflitti.
- Il deploy Cloudflare parte automaticamente dopo il push generato dal workflow di import.
- Per ora il progetto rimane semplice: niente CMS, niente database, solo JSON + file statici.

---

## Reader UI aggiornata per cataloghi grandi

La home non mostra più tutti i capitoli in una lista piatta. Ora usa:

- menu a tendina **Serie**;
- menu a tendina **Volume**;
- menu a tendina **Capitolo**;
- ricerca rapida capitolo/volume;
- pulsante **Continua lettura** salvato in `localStorage`;
- griglia limitata al volume selezionato.

Il reader del capitolo è ora pensato principalmente come **pagina singola**:

- freccia destra = pagina successiva;
- freccia sinistra = pagina precedente;
- da PC funzionano anche i tasti `ArrowRight` e `ArrowLeft`;
- da mobile funzionano swipe laterale e tap sui lati dell'immagine;
- a fine capitolo passa al capitolo successivo;
- a inizio capitolo passa all'ultima pagina del capitolo precedente;
- URL aggiornato con `page=`, quindi puoi condividere o ricaricare una pagina precisa;
- menu rapidi anche nel reader: **Volume**, **Capitolo**, **Pagina**.

Resta disponibile anche la modalità **Scroll verticale**, attivabile dal pulsante in alto nel reader.
