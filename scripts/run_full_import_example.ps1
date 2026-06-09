# Example PowerShell launcher for the one-time full historical import to Cloudflare R2.
# Run from the repository root.
# Fill the values below or set them as Windows user environment variables first.

$env:AUTHORIZED_MANGA_BASE_URL="https://your-authorized-source.example"
$env:I_CONFIRM_RIGHTS="true"
$env:CLOUDFLARE_ACCOUNT_ID="your_cloudflare_account_id"
$env:R2_BUCKET_NAME="op-reader-images"
$env:R2_PUBLIC_BASE_URL="https://static.lucahome.uk"
$env:R2_ACCESS_KEY_ID="your_r2_access_key_id"
$env:R2_SECRET_ACCESS_KEY="your_r2_secret_access_key"

# Optional custom URL template. Leave empty to use the default URL builder.
# $env:AUTHORIZED_MANGA_SOURCE_TEMPLATE="{base_url}/volumi/volume{volume_padded}/{chapter_padded}/{page_padded}.{extension}"

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
