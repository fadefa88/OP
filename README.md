
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
