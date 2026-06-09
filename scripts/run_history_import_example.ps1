# Example local historical import launcher for Windows PowerShell.
# Fill the values below, then run from the repo root:
#   .\scripts\run_history_import_example.ps1

$env:AUTHORIZED_MANGA_BASE_URL="https://your-authorized-source.example/path"
$env:I_CONFIRM_RIGHTS="true"
$env:CLOUDFLARE_ACCOUNT_ID="your_cloudflare_account_id"
$env:R2_BUCKET_NAME="op-reader-images"
$env:R2_PUBLIC_BASE_URL="https://static.lucahome.uk"
$env:R2_ACCESS_KEY_ID="your_r2_access_key_id"
$env:R2_SECRET_ACCESS_KEY="your_r2_secret_access_key"

python scripts/import_history_to_r2.py `
  --from-chapter 1 `
  --to-chapter 1184 `
  --extensions jpg,jpeg `
  --max-pages 45 `
  --min-pages 3 `
  --webp-quality 90 `
  --i-confirm-rights
