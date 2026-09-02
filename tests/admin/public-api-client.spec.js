const { test, expect } = require("@playwright/test");

async function loadPublicModules(page) {
  await page.goto("/real-estate-demo.html");
  return page.evaluate(async () => {
    window.UA_HOMES_API = window.location.origin;
    const api = await import("/lib/apiClient.js");
    const auth = await import("/lib/authSession.js");
    const catalog = await import("/lib/catalogApi.js");
    window.__publicModules = { api, auth, catalog };
  });
}

test("public API client parses success and preserves query names and credentials", async ({ page }) => {
  let request;
  await page.route("**/api/contract-success?*", async (route) => {
    request = route.request();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true }),
    });
  });
  await loadPublicModules(page);

  const result = await page.evaluate(() =>
    window.__publicModules.api.apiRequest("/contract-success", {
      query: { includeFacets: 1, minPrice: "", city: "Київ" },
    }),
  );

  expect(result).toEqual({ ok: true });
  expect(new URL(request.url()).searchParams.toString()).toBe(
    new URLSearchParams({ includeFacets: "1", city: "Київ" }).toString(),
  );
});

test("public API client returns a typed fallback error for malformed error bodies", async ({ page }) => {
  await page.route("**/api/contract-malformed", (route) =>
    route.fulfill({ status: 502, contentType: "text/html", body: "<h1>Bad gateway</h1>" }),
  );
  await loadPublicModules(page);

  const error = await page.evaluate(async () => {
    try {
      await window.__publicModules.api.apiRequest("/contract-malformed");
    } catch (caught) {
      return {
        name: caught.name,
        status: caught.status,
        payload: caught.payload,
        message: caught.message,
      };
    }
  });

  expect(error).toEqual({
    name: "ApiError",
    status: 502,
    payload: null,
    message: "Помилка запиту (502)",
  });
});

test("401 invokes auth expiry and clears both cached session forms", async ({ page }) => {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: "Unauthorized" }),
    }),
  );
  await loadPublicModules(page);

  const state = await page.evaluate(async () => {
    localStorage.setItem("uaDim.authToken", "stale");
    sessionStorage.setItem("uaDim.authToken", "stale");
    localStorage.setItem("uaDim.currentUser", "{}");
    let expired = false;
    try {
      await window.__publicModules.auth.fetchCurrentUser("stale", () => {
        expired = true;
        window.__publicModules.auth.clearAuthSessionCache();
      });
    } catch {}
    return {
      expired,
      localToken: localStorage.getItem("uaDim.authToken"),
      sessionToken: sessionStorage.getItem("uaDim.authToken"),
      user: localStorage.getItem("uaDim.currentUser"),
    };
  });

  expect(state).toEqual({ expired: true, localToken: null, sessionToken: null, user: null });
});

test("503 status remains available to the password-reset retry surface", async ({ page }) => {
  await page.route("**/api/auth/forgot-password", (route) =>
    route.fulfill({ status: 503, contentType: "text/plain", body: "Unavailable" }),
  );
  await loadPublicModules(page);

  const error = await page.evaluate(async () => {
    try {
      await window.__publicModules.auth.requestPasswordReset("user@example.test");
    } catch (caught) {
      return { name: caught.name, status: caught.status };
    }
  });

  expect(error).toEqual({ name: "ApiError", status: 503 });
});

test("latest-request coordinator aborts stale catalog work", async ({ page }) => {
  await loadPublicModules(page);

  const result = await page.evaluate(() => {
    const latest = window.__publicModules.api.createLatestRequest();
    const first = latest.begin();
    const second = latest.begin();
    return {
      firstAborted: first.signal.aborted,
      firstLatest: latest.isLatest(first.id),
      secondAborted: second.signal.aborted,
      secondLatest: latest.isLatest(second.id),
    };
  });

  expect(result).toEqual({
    firstAborted: true,
    firstLatest: false,
    secondAborted: false,
    secondLatest: true,
  });
});
