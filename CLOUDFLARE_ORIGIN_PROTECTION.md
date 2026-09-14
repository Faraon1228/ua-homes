# Cloudflare API origin protection

Cloudflare Workers proxy browser requests for `/api/*` to Railway and attach a
shared `X-UA-Edge-Token`. Railway rejects every other API request when
`UA_HOMES_EDGE_TOKEN` is configured. `/api/health` intentionally remains public
for Railway and external availability checks.

## One-time deployment

1. Generate a token locally. Do not copy it into source control:

   ```sh
   openssl rand -hex 32
   ```

2. Set that exact value as Railway service variable `UA_HOMES_EDGE_TOKEN`.
3. From `cloudflare/`, authenticate Wrangler, store the Cloudflare Worker secret,
   and deploy the Worker:

   ```sh
   npx wrangler login
   npx wrangler secret put UA_HOMES_EDGE_TOKEN
   npx wrangler deploy
   ```

4. Ensure `ua-dim.com` and `www.ua-dim.com` are proxied through the Cloudflare
   zone, then confirm the Worker routes in `wrangler.toml` are active.
5. Verify the public route, direct-origin rejection, and public health endpoint:

   ```sh
   curl -i https://ua-dim.com/api/listings
   curl -i https://backend-production-51964.up.railway.app/api/listings
   curl -i https://backend-production-51964.up.railway.app/api/health
   ```

   The public listing request must preserve its normal success response; direct
   Railway listing requests must return `403` and `code=edge_required`; direct
   Railway health checks must remain successful.

The Worker returns `503` with `code=edge_not_configured` when its secret is
missing, rather than forwarding an unauthenticated request. Deploy and verify
the Worker before removing any existing proxy with access to the token. The
Netlify frontend remains a static SPA; it no longer proxies `/api/*`.

Add Cloudflare WAF/rate-limit rules for `/api/auth/*`, `/api/analytics/*`, and
`/api/listings/*`. Retain the backend Redis-backed limiter as the second layer.
