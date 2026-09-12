const ORIGIN = "https://backend-production-51964.up.railway.app";

export default async function handler(request: Request): Promise<Response> {
  const token = Deno.env.get("UA_HOMES_EDGE_TOKEN")?.trim();
  if (!token) {
    return Response.json(
      { error: "API edge proxy is not configured.", code: "edge_not_configured" },
      { status: 503 },
    );
  }

  const incoming = new URL(request.url);
  const originUrl = new URL(incoming.pathname + incoming.search, ORIGIN);
  const headers = new Headers(request.headers);
  headers.set("X-UA-Edge-Token", token);

  return fetch(new Request(originUrl, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD"
      ? undefined
      : request.body,
    redirect: "manual",
  }));
}
