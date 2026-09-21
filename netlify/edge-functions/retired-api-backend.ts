import type { Config, Context } from "@netlify/edge-functions";

export default (_request: Request, _context: Context): Response =>
  Response.json(
    {
      error: "The legacy /api-backend/* route is retired. Use /api/*.",
      code: "legacy_api_backend_retired",
    },
    {
      status: 410,
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );

export const config: Config = {
  path: ["/api-backend", "/api-backend/*"],
};
