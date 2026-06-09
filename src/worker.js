const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=60, s-maxage=300"
};

function json(data, init = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    ...init,
    headers: {
      ...JSON_HEADERS,
      ...(init.headers || {})
    }
  });
}

function notFound(message = "Not found") {
  return json({ ok: false, error: message }, { status: 404, headers: { "cache-control": "no-store" } });
}

function badRequest(message = "Bad request") {
  return json({ ok: false, error: message }, { status: 400, headers: { "cache-control": "no-store" } });
}

function safeR2Key(key) {
  const decoded = decodeURIComponent(key || "").replace(/^\/+/, "");
  if (!decoded || decoded.includes("..") || decoded.includes("\\")) return null;
  return decoded;
}

async function fetchAssetJson(request, env, path) {
  const url = new URL(request.url);
  const assetUrl = new URL(path, url.origin);
  const response = await env.ASSETS.fetch(new Request(assetUrl.toString(), request));
  if (!response.ok) return null;
  return response.json();
}

async function fetchSplitManifest(request, env) {
  const indexPath = env.MANIFEST_INDEX_PATH || "/content/index.json";
  const legacyManifestPath = env.MANIFEST_PATH || "/content/manifest.json";

  const index = await fetchAssetJson(request, env, indexPath);
  if (!index) {
    const legacy = await fetchAssetJson(request, env, legacyManifestPath);
    if (!legacy) {
      return json({ ok: false, error: "Manifest not found", indexPath, legacyManifestPath }, { status: 500, headers: { "cache-control": "no-store" } });
    }
    return json({ ok: true, source: "legacy-manifest", data: legacy });
  }

  const assembled = structuredClone(index);

  for (const series of assembled.series || []) {
    const chapters = [];
    for (const volume of series.volumes || []) {
      const manifestPath = volume.manifest;
      if (!manifestPath) continue;
      const volumeManifest = await fetchAssetJson(request, env, manifestPath);
      if (!volumeManifest) continue;
      for (const chapter of volumeManifest.chapters || []) chapters.push(chapter);
    }
    chapters.sort((a, b) => Number(a.number || 0) - Number(b.number || 0));
    series.chapters = chapters;
  }

  return json({ ok: true, source: "split-manifest", data: assembled });
}

async function fetchVolumeManifest(request, env) {
  const url = new URL(request.url);
  const volume = url.searchParams.get("volume");
  if (!volume) return badRequest("Missing volume parameter");
  const padded = Number(volume) < 100 ? String(Number(volume)).padStart(3, "0") : String(Number(volume));
  const path = `/content/volumes/${padded}.json`;
  const data = await fetchAssetJson(request, env, path);
  if (!data) return notFound("Volume manifest not found");
  return json({ ok: true, source: "split-volume", data });
}

async function fetchR2Object(request, env, key) {
  if (!env.MANGA_R2) {
    return json({
      ok: false,
      error: "R2 binding not configured",
      hint: "This endpoint is optional. In production the reader uses the R2 public custom domain directly."
    }, { status: 501, headers: { "cache-control": "no-store" } });
  }

  const safeKey = safeR2Key(key);
  if (!safeKey) return badRequest("Invalid R2 key");

  const object = await env.MANGA_R2.get(safeKey);
  if (!object) return notFound("R2 object not found");

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "public, max-age=31536000, immutable");

  return new Response(object.body, { headers });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      return json({
        ok: true,
        service: env.SITE_NAME || "OP Reader",
        runtime: "cloudflare-workers",
        time: new Date().toISOString()
      }, { headers: { "cache-control": "no-store" } });
    }

    if (url.pathname === "/api/manifest" || url.pathname === "/api/chapters") {
      return fetchSplitManifest(request, env);
    }

    if (url.pathname === "/api/volume") {
      return fetchVolumeManifest(request, env);
    }

    if (url.pathname.startsWith("/api/r2/")) {
      const key = url.pathname.replace("/api/r2/", "");
      return fetchR2Object(request, env, key);
    }

    return env.ASSETS.fetch(request);
  }
};
