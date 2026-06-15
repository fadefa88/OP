
## ntfy chapter notifications

The hourly GitHub Action sends a push notification through ntfy only when a new chapter is imported, uploaded to R2, and the JSON manifest commit is pushed successfully.

Default topic configured in `.github/workflows/daily-download.yml`:

```text
ldf-op-reader-cagnettoasd123
```

Optional override: add `NTFY_TOPIC` as a GitHub Actions secret or variable. The notification opens the new chapter directly on `https://manga.lucahome.uk`.

## One Man Punch / One Punch Man integration

This repository now supports a second series with `seriesId = opm` and title `One Man Punch`.

R2 keys use the same production convention, with a different prefix:

```text
opm/vol-001/chapter-0001/page-001.webp
opm/vol-001/chapter-0001/page-001.jpg
```

The homepage reads the combined manifest and displays both available series. Each series has its own volume and chapter picker.

### GitHub Actions

- `Manual Import One Man Punch Chapter to R2`: imports a single One Man Punch chapter.
- `Mass Import One Man Punch Archive to R2`: imports a range of One Man Punch chapters in batches.
- `Scan New One Man Punch Chapter to R2 Hourly`: checks every hour for the next One Man Punch chapter, uploads images to R2, commits JSON only, deploys Cloudflare, and sends ntfy notification only if something new was imported.

Default source base:

```text
https://onepiecepower.com/manga8/one-punch-man
```

Default direct image URL pattern:

```text
{base_url}/volumi/volume{volume_padded}/{chapter_padded}/{page_padded}.{extension}
```

For chapter 1 page 1, this becomes:

```text
https://onepiecepower.com/manga8/one-punch-man/volumi/volume001/001/01.jpg
```

This is the same direct-image importer and path convention used for One Piece; only the source base URL and the R2 prefix change.

Optional repository variables:

```text
OPM_AUTHORIZED_MANGA_BASE_URL
OPM_AUTHORIZED_MANGA_SOURCE_TEMPLATE
OPM_SERIES_TITLE
```

Existing required secrets/variables are reused:

```text
I_CONFIRM_RIGHTS=true
R2_BUCKET_NAME
R2_PUBLIC_BASE_URL
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
NTFY_TOPIC
```

## One Punch Man import logic

One Punch Man uses a different direct-image source path from One Piece:

```text
https://onepiecepower.com/manga8/one-punch-man/volume01/capitolo01/01.jpg
```

The importer does not require a fixed chapter-per-volume map. It scans source volumes and local chapter folders, then assigns sequential reader/global chapter numbers:

```text
source volume01/capitolo01 -> reader chapter 1
source volume01/capitolo02 -> reader chapter 2
...
source volume02/capitolo01 -> next reader chapter
```

Each imported chapter stores both values in the manifest:

```json
"sourceVolume": 1,
"sourceChapter": 1
```

R2 paths remain normalized:

```text
opm/vol-001/chapter-0001/page-001.webp
opm/vol-001/chapter-0001/page-001.jpg
```

Workflows:

```text
Manual Import One Punch Man Chapter to R2
Mass Import One Punch Man Archive to R2
Scan New One Punch Man Chapter to R2 Hourly
```

Recommended first test:

```text
source_volume: 1
source_chapter: 1
max_pages: 80
min_pages: 3
overwrite: false
```

Recommended mass import:

```text
from_source_volume: 1
to_source_volume: 37
total_chapters: 236
max_source_chapters_per_volume: 30
max_pages: 80
min_pages: 3
overwrite: false
```


### One Punch Man volume transition rule

For OPM, source paths use `volumeXX/capitoloYY/page.jpg`. Because the number of source-local chapters per volume is not fixed, the importer now uses this rule:

```text
try next local chapter in the current source volume
if 3 consecutive source-local chapters are missing/invalid
→ move to the next source volume
→ resume from the last valid source chapter number, not from capitolo01

Example:
volume01/capitolo09 is the last valid chapter
volume01/capitolo10, 11 and 12 are missing
→ next scan starts from volume02/capitolo09
```

The value is configurable in GitHub Actions with `missing_chapters_to_next_volume`, default `3`.

## Import manga terminati nel repository GitHub

Per Naruto, Solo Leveling e Attack on Titan le immagini vengono salvate nel repository, non su R2.

Percorso immagini nel repo/deploy:

```text
public/manga-local/<series>/vol-XXX/chapter-XXXX/page-XXX.webp
public/manga-local/<series>/vol-XXX/chapter-XXXX/page-XXX.jpg
```

Serie configurate:

| Serie | ID | Sorgente | Capitoli | Volumi |
|---|---|---|---:|---:|
| Naruto | `naruto` | `https://onepiecepower.com/manga8/naruto-a/volume01/capitolo01/01.jpg` | 700 | 72 |
| Solo Leveling | `solo-leveling` | `https://onepiecepower.com/manga8/solo-leveling-a/volume01/capitolo00/01.jpg` | 200 | 3 |
| Attack on Titan | `aot` | `https://onepiecepower.com/manga8/attack-on-titan-d/volume01/capitolo01/01.jpg` | 139 + extra | 34 + 6 extra |

Workflow:

```text
Actions → Mass Import Finished Manga to GitHub Repo
```

Logica volume/capitolo:

```text
1. Lo script prova il capitolo sorgente successivo nello stesso volume.
2. Se trova immagini valide, salva il capitolo e incrementa il capitolo globale del reader.
3. Se trova 3 capitoli sorgente consecutivi assenti, passa al volume successivo.
4. Quando passa al volume successivo, non riparte da capitolo01: riparte dall’ultimo capitolo sorgente valido scansionato.
5. Per Solo Leveling il primo capitolo sorgente è capitolo00.
6. Per Attack on Titan, dopo il capitolo 139 importa gli extra 139-1, 139-2, 139-3, 139-4, 139-5 e 139-6.
```

Parametri consigliati:

```text
series: naruto / solo-leveling / aot
batch_size: 10
max_batches: 3
max_pages: 0
min_pages: 3
missing_chapters_to_next_volume: 3
webp_quality: 82
image_strategy: best-size
overwrite: false
deploy_after: true
```

Nota operativa: GitHub e Cloudflare Static Assets non sono storage pensati per archivi manga molto grandi. Se il deploy fallisce per numero/dimensione asset, riduci il batch oppure sposta nuovamente le immagini su object storage.
