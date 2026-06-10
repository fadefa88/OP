const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=60, s-maxage=600"
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

function pad3(value) {
  return String(Number(value)).padStart(3, "0");
}

function pad4(value) {
  return String(Number(value)).padStart(4, "0");
}

function publicUrlForKey(env, request, key) {
  const explicitBase = (env.R2_PUBLIC_BASE_URL || "").replace(/\/$/, "");
  if (explicitBase) return `${explicitBase}/${key}`;
  const url = new URL(request.url);
  return `${url.origin}/api/r2/${key}`;
}

async function fetchAssetJson(request, env, path) {
  const url = new URL(request.url);
  const assetUrl = new URL(path, url.origin);
  const response = await env.ASSETS.fetch(new Request(assetUrl.toString(), request));
  if (!response.ok) return null;
  return response.json();
}

async function listAllR2Objects(env, prefix) {
  const objects = [];
  let cursor;

  do {
    const result = await env.MANGA_R2.list({
      prefix,
      cursor,
      limit: 1000
    });

    objects.push(...(result.objects || []));
    cursor = result.truncated ? result.cursor : undefined;
  } while (cursor);

  return objects;
}

function addPage(chapterPages, pageNumber, page) {
  const existing = chapterPages.get(pageNumber);
  if (!existing) {
    chapterPages.set(pageNumber, page);
    return;
  }

  const existingSize = Number(existing.size ?? Number.MAX_SAFE_INTEGER);
  const newSize = Number(page.size ?? Number.MAX_SAFE_INTEGER);

  if (newSize < existingSize) {
    chapterPages.set(pageNumber, page);
    return;
  }

  if (newSize === existingSize && page.ext === "webp" && existing.ext !== "webp") {
    chapterPages.set(pageNumber, page);
  }
}

async function buildR2Manifest(request, env) {
  if (!env.MANGA_R2) return null;

  const prefix = `${(env.R2_PUBLIC_PREFIX || "op").replace(/^\/+|\/+$/g, "")}/`;
  const objects = await listAllR2Objects(env, prefix);
  const keyPattern = new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}vol-(\\d+)\\/chapter-(\\d+)\\/page-(\\d+)\\.(webp|jpe?g|png)$`, "i");
  const volumes = new Map();
  let latestObjectUploadedAt = null;

  for (const object of objects) {
    if (object.uploaded) {
      const uploadedAt = new Date(object.uploaded);
      if (!Number.isNaN(uploadedAt.getTime()) && (!latestObjectUploadedAt || uploadedAt > latestObjectUploadedAt)) {
        latestObjectUploadedAt = uploadedAt;
      }
    }
    const match = object.key.match(keyPattern);
    if (!match) continue;

    const volumeNumber = Number(match[1]);
    const chapterNumber = Number(match[2]);
    const pageNumber = Number(match[3]);
    const ext = match[4].toLowerCase() === "jpeg" ? "jpg" : match[4].toLowerCase();

    if (!Number.isFinite(volumeNumber) || !Number.isFinite(chapterNumber) || !Number.isFinite(pageNumber)) continue;

    if (!volumes.has(volumeNumber)) volumes.set(volumeNumber, new Map());
    const chapters = volumes.get(volumeNumber);
    if (!chapters.has(chapterNumber)) chapters.set(chapterNumber, new Map());

    addPage(chapters.get(chapterNumber), pageNumber, {
      src: publicUrlForKey(env, request, object.key),
      key: object.key,
      number: pageNumber,
      ext,
      size: object.size || null
    });
  }

  const volumeEntries = [];
  const chapterEntries = [];
  const sortedVolumeNumbers = [...volumes.keys()].sort((a, b) => a - b);

  for (const volumeNumber of sortedVolumeNumbers) {
    const chapters = volumes.get(volumeNumber);
    const sortedChapterNumbers = [...chapters.keys()].sort((a, b) => a - b);
    const volumeChapters = [];

    for (const chapterNumber of sortedChapterNumbers) {
      const pagesMap = chapters.get(chapterNumber);
      const pages = [...pagesMap.entries()]
        .sort(([a], [b]) => a - b)
        .map(([, page]) => ({ src: page.src, key: page.key }));

      if (!pages.length) continue;

      const chapter = {
        id: `chapter-${pad4(chapterNumber)}`,
        number: chapterNumber,
        volume: volumeNumber,
        title: `Capitolo ${chapterNumber}`,
        pages
      };

      volumeChapters.push(chapter);
      chapterEntries.push(chapter);
    }

    if (!volumeChapters.length) continue;

    volumeEntries.push({
      volume: volumeNumber,
      fromChapter: volumeChapters[0].number,
      toChapter: volumeChapters.at(-1).number,
      chaptersCount: volumeChapters.length,
      source: "r2"
    });
  }

  chapterEntries.sort((a, b) => Number(a.number || 0) - Number(b.number || 0));

  const generatedAt = new Date().toISOString();
  const lastUpdatedAt = latestObjectUploadedAt ? latestObjectUploadedAt.toISOString() : generatedAt;

  return {
    schemaVersion: 3,
    generatedAt,
    lastUpdatedAt,
    source: "r2-dynamic-listing",
    r2: {
      prefix: prefix.replace(/\/$/, ""),
      publicBaseUrl: env.R2_PUBLIC_BASE_URL || null,
      objectsScanned: objects.length
    },
    series: [
      {
        id: env.SERIES_ID || "op",
        title: env.SERIES_TITLE || "© LDF",
        description: "Archivio ordinato da Cloudflare R2 per volume, capitolo e pagina.",
        cover: chapterEntries[0]?.pages?.[0]?.src || null,
        latestChapter: chapterEntries.at(-1)?.number || null,
        chaptersCount: chapterEntries.length,
        lastUpdatedAt,
        volumes: volumeEntries,
        chapters: chapterEntries
      }
    ]
  };
}

async function cachedR2Manifest(request, env, ctx) {
  const url = new URL(request.url);
  const refresh = url.searchParams.get("refresh") === "1";
  const ttl = Number(env.R2_MANIFEST_CACHE_SECONDS || 600);
  const cacheKey = new Request(`${url.origin}/api/manifest:r2:${env.R2_PUBLIC_PREFIX || "op"}:v4`);
  const cache = caches.default;

  if (!refresh) {
    const cached = await cache.match(cacheKey);
    if (cached) return cached;
  }

  const manifest = await buildR2Manifest(request, env);
  if (!manifest) return null;

  const response = json({ ok: true, source: "r2-dynamic-listing", data: manifest }, {
    headers: {
      "cache-control": `public, max-age=60, s-maxage=${ttl}`
    }
  });

  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
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

  const assembled = JSON.parse(JSON.stringify(index));
  assembled.lastUpdatedAt = assembled.lastUpdatedAt || assembled.generatedAt || null;

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
    series.lastUpdatedAt = series.lastUpdatedAt || assembled.lastUpdatedAt || null;
  }

  return json({ ok: true, source: "split-manifest", data: assembled });
}

async function fetchManifest(request, env, ctx) {
  const mode = String(env.R2_LIBRARY_MODE || "dynamic").toLowerCase();

  if (mode === "dynamic" || mode === "r2") {
    const r2Response = await cachedR2Manifest(request, env, ctx);
    if (r2Response) return r2Response;
  }

  return fetchSplitManifest(request, env);
}

async function fetchVolumeManifest(request, env) {
  const url = new URL(request.url);
  const volume = url.searchParams.get("volume");
  if (!volume) return badRequest("Missing volume parameter");

  if (String(env.R2_LIBRARY_MODE || "dynamic").toLowerCase() === "dynamic" && env.MANGA_R2) {
    const manifest = await buildR2Manifest(request, env);
    const series = manifest?.series?.[0];
    const chapters = (series?.chapters || []).filter((chapter) => String(chapter.volume) === String(Number(volume)));
    if (!chapters.length) return notFound("Volume not found in R2");
    return json({
      ok: true,
      source: "r2-dynamic-volume",
      data: {
        volume: Number(volume),
        chapters
      }
    });
  }

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
      hint: "Configure the MANGA_R2 binding in wrangler.jsonc."
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
        service: env.SITE_NAME || "© LDF",
        runtime: "cloudflare-workers",
        r2LibraryMode: env.R2_LIBRARY_MODE || "dynamic",
        hasR2Binding: Boolean(env.MANGA_R2),
        time: new Date().toISOString()
      }, { headers: { "cache-control": "no-store" } });
    }

    if (url.pathname === "/api/manifest" || url.pathname === "/api/chapters" || url.pathname === "/api/r2/library") {
      return fetchManifest(request, env, ctx);
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
