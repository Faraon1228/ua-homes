# Netlify edge proxy for the Railway API

The Netlify Edge Function at `/api/*` forwards requests to Railway and adds
the private `X-UA-Edge-Token` header. The same token must already be set in
Railway as `UA_HOMES_EDGE_TOKEN`.

## Configure the Netlify secret before deploying this route

In Netlify, open:

**Project configuration → Environment variables → Add a variable**

Create:

```text
UA_HOMES_EDGE_TOKEN=<the same value configured in Railway>
```

Use the production scope. Never commit the value or put it in `netlify.toml`.

After the variable is saved, deploy the branch containing this function. Verify:

```sh
curl -i https://ua-dim.com/api/health
curl -i https://backend-production-51964.up.railway.app/api/listings
```

The public domain request must return `200` (or the endpoint's normal response),
while the direct Railway request must return `403` with `code=edge_required`.

Do not merge this change until the Netlify variable exists. The function fails
closed with `503 edge_not_configured` if the variable is absent.
