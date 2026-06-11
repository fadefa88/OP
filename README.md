
## ntfy chapter notifications

The hourly GitHub Action sends a push notification through ntfy only when a new chapter is imported, uploaded to R2, and the JSON manifest commit is pushed successfully.

Default topic configured in `.github/workflows/daily-download.yml`:

```text
ldf-op-reader-cagnettoasd123
```

Optional override: add `NTFY_TOPIC` as a GitHub Actions secret or variable. The notification opens the new chapter directly on `https://manga.lucahome.uk`.

## Nota deploy automatico dopo import R2

I workflow di import (`daily-download.yml` e `manual-import-chapter-r2.yml`) caricano le immagini su R2 e committano solo i manifest JSON. Subito dopo un push riuscito eseguono anche `wrangler deploy`, perché i push generati da `GITHUB_TOKEN` non fanno necessariamente partire un secondo workflow di deploy. In questo modo il sito vede subito il nuovo `public/content/manifest.json` senza attendere un deploy separato.

