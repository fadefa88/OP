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

async function fetchManifest(request, env) {
  const manifestPath = env.MANIFEST_PATH || "/content/manifest.json";
  const url = new URL(request.url);
  const manifestUrl = new URL(manifestPath, url.origin);
  const response = await env.ASSETS.fetch(new Request(manifestUrl.toString(), request));

  if (!response.ok) {
    return json({ ok: false, error: "Manifest not found", manifestPath }, { status: 500, headers: { "cache-control": "no-store" } });
  }

  const data = await response.json();
  return json({ ok: true, source: "static-assets", data });
}

async function fetchR2Object(request, env, key) {
  if (!env.MANGA_R2) {
    return json({
      ok: false,
      error: "R2 binding not configured",
      hint: "Uncomment r2_buckets in wrangler.jsonc and bind a bucket as MANGA_R2."
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
        service: env.SITE_NAME || "Manga Reader",
        runtime: "cloudflare-workers",
        time: new Date().toISOString()
      }, { headers: { "cache-control": "no-store" } });
    }

    if (url.pathname === "/api/manifest" || url.pathname === "/api/chapters") {
      return fetchManifest(request, env);
    }

    if (url.pathname.startsWith("/api/r2/")) {
      const key = url.pathname.replace("/api/r2/", "");
      return fetchR2Object(request, env, key);
    }

    return env.ASSETS.fetch(request);
  }
};
