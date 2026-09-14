const ORIGIN = "https://backend-production-51964.up.railway.app";

export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);
    if (!incoming.pathname.startsWith("/api/")) {
      return new Response("Not found", { status: 404 });
    }

    const edgeToken = env.UA_HOMES_EDGE_TOKEN?.trim();
    if (!edgeToken) {
      return Response.json(
        { error: "API edge proxy is not configured.", code: "edge_not_configured" },
        { status: 503 },
      );
    }

    const originUrl = new URL(incoming.pathname + incoming.search, ORIGIN);
    const headers = new Headers(request.headers);
    headers.set("X-UA-Edge-Token", edgeToken);

    return fetch(new Request(originUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD"
        ? undefined
        : request.body,
      redirect: "manual",
    }));
  },
};
