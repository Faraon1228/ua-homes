import type { Config, Context } from "@netlify/edge-functions";

// Netlify DNS-hosted domains (ua-dim.com) cannot front Cloudflare, so this
// edge function replaces the Cloudflare Worker as the trusted proxy that
// attaches the shared X-UA-Edge-Token before forwarding to Railway. Railway
// rejects unauthenticated /api/* requests (except /api/health) with
// 403 edge_required — see backend/app.py and CLOUDFLARE_ORIGIN_PROTECTION.md.
const ORIGIN = "https://backend-production-51964.up.railway.app";

const HOP_BY_HOP_HEADERS = [
  "host",
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "content-length",
];

export default async (request: Request, _context: Context): Promise<Response> => {
  const incoming = new URL(request.url);

  const edgeToken = Netlify.env.get("UA_HOMES_EDGE_TOKEN")?.trim();
  if (!edgeToken) {
    // Fail closed: never forward to Railway without the shared secret.
    return Response.json(
      { error: "API edge proxy is not configured.", code: "edge_not_configured" },
      { status: 503 },
    );
  }

  const originUrl = new URL(incoming.pathname + incoming.search, ORIGIN);

  const headers = new Headers(request.headers);
  for (const name of HOP_BY_HOP_HEADERS) {
    headers.delete(name);
  }
  headers.set("X-UA-Edge-Token", edgeToken);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  return fetch(originUrl, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    redirect: "manual",
  });
};

export const config: Config = {
  path: "/api/*",
};
