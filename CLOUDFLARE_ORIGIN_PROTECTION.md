# Cloudflare origin protection

The API is protected by a shared secret between the Cloudflare Worker and
Railway. The secret is never stored in Git.

## One-time setup

1. Create a long random token locally:

   ```sh
   openssl rand -hex 32
   ```

2. Add the same value to Railway as `UA_HOMES_EDGE_TOKEN`.
3. From `cloudflare/`, install Wrangler if needed and store the secret:

   ```sh
   npx wrangler secret put UA_HOMES_EDGE_TOKEN
   npx wrangler deploy
   ```

4. Verify the Worker route is active, then verify:

   ```sh
   curl -i https://ua-dim.com/api/health
   curl -i https://backend-production-51964.up.railway.app/api/listings
   ```

   The first request must remain successful. The second must return `403`
   with `{"code":"edge_required"}` (the health endpoint is intentionally
   public for deployment monitoring).

5. Add Cloudflare WAF/rate-limit rules for `/api/auth/*`,
   `/api/analytics/*`, and `/api/listings/*`. Keep the Redis-backed
   application limiter enabled as the second layer.

The API redirect was removed from `netlify.toml`, so the Worker must be
deployed before this branch is merged or the frontend API will be unavailable.
