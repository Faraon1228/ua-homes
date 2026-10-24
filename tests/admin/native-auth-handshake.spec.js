const { test, expect } = require("@playwright/test");

test.use({ serviceWorkers: "block" });

const user = { id: 7, name: "Тест", email: "test@example.test", account_type: "owner" };
const json = (route, body, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__nativeAuth = [];
    window.UaDimAuth = { postMessage: (message) => window.__nativeAuth.push(JSON.parse(message)) };
  });
  await page.route("**/api/listings?*", (route) => json(route, { listings: [], total: 0, has_more: false }));
  await page.route("**/api/inquiries", (route) => json(route, { inquiries: [] }));
});

const seedStale = (page, token) =>
  page.addInitScript((value) => {
    if (sessionStorage.getItem("__seeded")) return;
    sessionStorage.setItem("__seeded", "1");
    sessionStorage.setItem("uaDim.authToken", value);
    localStorage.setItem("uaDim.currentUser", JSON.stringify({ id: 7, name: "Тест", email: "test@example.test", account_type: "owner" }));
  }, token);
const nativeReady = (page) =>
  page.evaluate(() => {
    window.__uaDimAuthReady = true;
    window.dispatchEvent(new Event("uadim-auth-ready"));
  });
const messages = (page) => page.evaluate(() => window.__nativeAuth);

test("nothing is validated or sent to native before the restore-ready boundary", async ({ page }) => {
  await seedStale(page, "token-a");
  const meAuth = [];
  await page.route("**/api/auth/me", (route) => {
    meAuth.push(route.request().headers().authorization);
    return json(route, { user });
  });
  await page.goto("/real-estate-demo.html?seller=1");
  await expect(page.locator("#header-logout-cta")).toBeVisible();
  await page.waitForTimeout(600);
  expect(meAuth).toEqual([]);
  expect(await messages(page)).toEqual([]);

  // Native restore: secure token B is written, then the page reloads before being declared ready.
  await page.evaluate(() => {
    sessionStorage.setItem("uaDim.authToken", "token-b");
    localStorage.setItem("uaDim.authToken", "token-b");
  });
  await page.reload();
  await expect(page.locator("#header-logout-cta")).toBeVisible();
  expect(meAuth).toEqual([]);
  await nativeReady(page);
  await expect.poll(() => meAuth).toEqual(["Bearer token-b"]);
  expect(await messages(page)).toEqual([{ version: 1, type: "auth", token: "token-b" }]);
});

test("a 401 for the stale token arriving after native restore wrote the secure token keeps it", async ({ page }) => {
  await seedStale(page, "token-a");
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let seen = false;
  await page.route("**/api/auth/me", async (route) => {
    seen = true;
    await gate;
    return json(route, { error: "Unauthorized" }, 401);
  });
  await page.goto("/real-estate-demo.html?seller=1");
  await nativeReady(page);
  await expect.poll(() => seen).toBe(true);
  // Native apply-restore runs in the still-live document, before the reload.
  await page.evaluate(() => {
    sessionStorage.setItem("uaDim.authToken", "token-b");
    localStorage.setItem("uaDim.authToken", "token-b");
  });
  release();
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => sessionStorage.getItem("uaDim.authToken"))).toBe("token-b");
  expect((await messages(page)).some((message) => message.token === null)).toBe(false);
});

test("shells that never signal ready are released by the timeout", async ({ page }) => {
  await seedStale(page, "token-a");
  const meAuth = [];
  await page.route("**/api/auth/me", (route) => {
    meAuth.push(route.request().headers().authorization);
    return json(route, { user });
  });
  await page.goto("/real-estate-demo.html?seller=1");
  await expect.poll(() => meAuth[0], { timeout: 15000 }).toBe("Bearer token-a");
});

test("explicit user logout still reaches native immediately", async ({ page }) => {
  await seedStale(page, "web-token");
  await page.route("**/api/auth/me", (route) => json(route, { user }));
  await page.goto("/real-estate-demo.html?seller=1");
  await nativeReady(page);
  await page.locator("#header-logout-cta").click();
  await expect.poll(() => messages(page)).toEqual([
    { version: 1, type: "auth", token: "web-token" },
    { version: 1, type: "auth", token: null },
  ]);
});

test("a late 401 for the previous token does not sign out the newer login", async ({ page }) => {
  await seedStale(page, "token-a");
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/auth/me", async (route) => {
    const auth = route.request().headers().authorization || "";
    if (auth.endsWith("token-a")) {
      await gate;
      return json(route, { error: "Unauthorized" }, 401);
    }
    return json(route, { user });
  });
  await page.route("**/api/auth/login", (route) => json(route, { token: "token-b", user }));
  await page.goto("/real-estate-demo.html?seller=1");
  await nativeReady(page);
  await page.locator("#header-logout-cta").click();
  await page.locator("#auth-email").fill("test@example.test");
  await page.locator("#auth-password").fill("not-a-real-password");
  await page.getByRole("button", { name: "Увійти", exact: true }).last().click();
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem("uaDim.authToken"))).toBe("token-b");
  release();
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => sessionStorage.getItem("uaDim.authToken"))).toBe("token-b");
  expect(await messages(page)).toEqual([
    { version: 1, type: "auth", token: "token-a" },
    { version: 1, type: "auth", token: null },
    { version: 1, type: "auth", token: "token-b" },
  ]);
});
