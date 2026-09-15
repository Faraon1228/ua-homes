# API client contract

All browser and mobile callers use the canonical `/api/*` contract. Public
browser calls are same-origin and therefore pass through the Netlify Edge
proxy; the edge function is the only layer allowed to add `X-UA-Edge-Token`.
The token is never embedded in browser bundles, Flutter builds, or runtime
configuration exposed to clients.

| Concern | Canonical behavior | Compatibility notes |
| --- | --- | --- |
| Base URL | Browser defaults to the current origin; local browser development uses `http://127.0.0.1:5050`. `UA_HOMES_API` may override the origin and may include `/api` once. Mobile receives `UA_DIM_API_BASE_URL` at build time. | Existing `UA_HOMES_API` overrides remain supported. |
| API prefix | Clients add exactly one `/api`; admin requests use `/api/admin`. | Callers pass paths such as `/listings`, not `/api/listings`. |
| Authentication | Web public compatibility callers may pass a user Bearer token. Admin uses same-origin httpOnly session cookies. Mobile push calls pass the current user Bearer token. | Edge tokens are never accepted as client auth. |
| CSRF | Admin mutating requests echo the in-memory `csrf_token` returned by login/session as `X-CSRF-Token`; the cookie remains httpOnly. | No CSRF header is sent for safe methods. |
| Edge token | Only `netlify/edge-functions/api-proxy.ts` injects `X-UA-Edge-Token`; Railway rejects direct `/api/*` access. | `/api/health` remains backend's public health exception. |
| Timeout/retry | Requests time out after 15 seconds by default. There is no automatic retry; callers choose whether an operation is safe to repeat. Latest-request search work aborts stale requests. | `timeout: 0` disables the client timeout. |
| Errors | Non-2xx responses throw `ApiError` with `status` and parsed `payload`; malformed bodies produce `payload: null`. Network failures use status `0`; timeout uses `408`; caller aborts remain `AbortError`. | Existing unauthorized callbacks remain supported. |
| Uploads | FormData is sent without a JSON content type so the browser supplies the multipart boundary. | Admin `api.upload` remains the compatibility adapter. |

## Migration policy

New callers must use the canonical client and relative `/api/*` routes. Legacy
helpers remain in place during PR2 so verified in-repo callers can migrate
without changing unrelated features.
