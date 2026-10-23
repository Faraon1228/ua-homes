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

test("cold start with an empty web session does not tell native to clear its secure token", async ({ page }) => {
  await page.goto("/real-estate-demo.html?seller=1");
  await expect(page.locator("#auth-email")).toBeVisible();
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => window.__nativeAuth)).toEqual([]);
});

test("cold start with a stale web token does not overwrite the native token either", async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("uaDim.authToken", "stale-web-token");
    localStorage.setItem("uaDim.currentUser", JSON.stringify({ id: 7, name: "Тест", email: "test@example.test", account_type: "owner" }));
  });
  await page.route("**/api/auth/me", (route) => json(route, { user }));
  await page.goto("/real-estate-demo.html?seller=1");
  await expect(page.locator("#header-logout-cta")).toBeVisible();
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => window.__nativeAuth)).toEqual([]);
});

test("explicit user logout still reaches native immediately", async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("uaDim.authToken", "web-token");
    localStorage.setItem("uaDim.currentUser", JSON.stringify({ id: 7, name: "Тест", email: "test@example.test", account_type: "owner" }));
  });
  await page.route("**/api/auth/me", (route) => json(route, { user }));
  await page.goto("/real-estate-demo.html?seller=1");
  await page.locator("#header-logout-cta").click();
  await expect.poll(() => page.evaluate(() => window.__nativeAuth)).toEqual([
    { version: 1, type: "auth", token: null },
  ]);
});

test("a late 401 for the previous token does not sign out the newer login", async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem("uaDim.authToken", "token-a");
    localStorage.setItem("uaDim.currentUser", JSON.stringify({ id: 7, name: "Тест", email: "test@example.test", account_type: "owner" }));
  });
  let releaseA;
  const aGate = new Promise((resolve) => { releaseA = resolve; });
  await page.route("**/api/auth/me", async (route) => {
    const auth = route.request().headers().authorization || "";
    if (auth.endsWith("token-a")) {
      await aGate;
      return json(route, { error: "Unauthorized" }, 401);
    }
    return json(route, { user });
  });
  await page.route("**/api/auth/login", (route) => json(route, { token: "token-b", user }));
  await page.goto("/real-estate-demo.html?seller=1");
  await page.locator("#header-logout-cta").click();
  await page.locator("#auth-email").fill("test@example.test");
  await page.locator("#auth-password").fill("not-a-real-password");
  await page.getByRole("button", { name: "Увійти", exact: true }).last().click();
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem("uaDim.authToken"))).toBe("token-b");
  releaseA();
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => sessionStorage.getItem("uaDim.authToken"))).toBe("token-b");
  expect(await page.evaluate(() => window.__nativeAuth)).toEqual([
    { version: 1, type: "auth", token: null },
    { version: 1, type: "auth", token: "token-b" },
  ]);
});
