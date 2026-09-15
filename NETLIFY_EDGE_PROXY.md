# Netlify Edge Function API proxy

`ua-dim.com` is delegated to **Netlify DNS**, so the Cloudflare Worker in
`cloudflare/` (see `CLOUDFLARE_ORIGIN_PROTECTION.md`) cannot front the domain.
Netlify's plain `/api/*` redirect forwarded to Railway without the shared
`X-UA-Edge-Token`, so Railway rejected every request with
`403 edge_required` (Railway only allows unauthenticated access to
`/api/health`; see `backend/app.py`).

`netlify/edge-functions/api-proxy.ts` replaces that redirect: it runs on
Netlify's edge network, proxies `/api/*` to
`https://backend-production-51964.up.railway.app/api/*`, preserves the
method/query string/body, and attaches `X-UA-Edge-Token` from a Netlify
environment variable. Netlify Edge Functions execute **before** redirects and
returning a `Response` ends the request chain, so the old unauthenticated
`/api/*` redirect was removed from `netlify.toml` — there is no duplicate or
conflicting route.

If the secret is missing, the function fails closed with a JSON `503`
(`{"error": "...", "code": "edge_not_configured"}`) instead of forwarding an
unauthenticated request.

## One-time deployment

1. Generate a token (or reuse the one already set on Railway):

   ```sh
   openssl rand -hex 32
   ```

2. Ensure Railway's `UA_HOMES_EDGE_TOKEN` service variable has that exact
   value (it already does if the Cloudflare Worker is deployed).
3. In the Netlify UI: **Site settings → Environment variables → Add a
   variable**.
   - Key: `UA_HOMES_EDGE_TOKEN`
   - Value: the same token as Railway
   - Scopes: enable **Functions** (edge functions only read variables scoped
     to Functions) — see
     https://docs.netlify.com/build/edge-functions/environment-variables/.
   - Do not commit this value to source control.
4. Trigger a new deploy (environment variable changes only take effect on
   the next build/deploy).
5. Verify:

   ```sh
   curl -i https://ua-dim.com/api/listings
   curl -i https://backend-production-51964.up.railway.app/api/listings
   curl -i https://ua-dim.com/api/health
   ```

   `ua-dim.com/api/listings` must return its normal successful response,
   direct Railway `/api/listings` requests must still return `403
   edge_required`, and `/api/health` must stay publicly reachable through
   both paths.

If `UA_HOMES_EDGE_TOKEN` is ever unset on Netlify, `/api/*` returns
`503 edge_not_configured` rather than silently forwarding unauthenticated
traffic.
