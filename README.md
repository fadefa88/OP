
## ntfy chapter notifications

The hourly GitHub Action sends a push notification through ntfy only when a new chapter is imported, uploaded to R2, and the JSON manifest commit is pushed successfully.

Default topic configured in `.github/workflows/daily-download.yml`:

```text
ldf-op-reader-cagnettoasd123
```

Optional override: add `NTFY_TOPIC` as a GitHub Actions secret or variable. The notification opens the new chapter directly on `https://manga.lucahome.uk`.
