const { test, expect } = require("@playwright/test");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const python = process.env.UA_TEST_PYTHON || "python3";
const pages = JSON.parse(execFileSync(python, ["tests/fixtures/render-listing-pages.py"], { cwd: root, encoding: "utf8" }));
const ids = Object.keys(pages);
const shell = fs.readFileSync(path.join(root, "web/real-estate-demo.html"), "utf8");
const nativeBackScript = fs.readFileSync(path.join(root, "apps/ua_dim/lib/webview/navigation_policy.dart"), "utf8")
  .match(/uaDimListingBackScript = '''([\s\S]*?)'''/)[1];

test.use({ serviceWorkers: "block" });

async function setup(page) {
  await page.addInitScript(() => {
    localStorage.setItem("uaDim.privacyConsent.v1", JSON.stringify({ version: 1, analytics: false }));
    localStorage.setItem("uaDim.pwaDismissedUntil", String(Date.now() + 86400000));
    localStorage.setItem("re.cityFilter", "Київ");
    localStorage.setItem("re.minRooms", "2");
    localStorage.setItem("re.minPrice", "50000");
  });
  await page.route("**/app?*", (route) => route.fulfill({ contentType: "text/html", body: shell }));
  await page.route("**/app", (route) => route.fulfill({ contentType: "text/html", body: shell }));
  await page.context().route("**/listing/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop();
    const rendered = pages[id];
    return route.fulfill({
      contentType: "text/html",
      headers: { "Content-Security-Policy": rendered.csp, "Referrer-Policy": "strict-origin-when-cross-origin" },
      body: rendered.html,
    });
  });
  const requests = [];
  await page.route("**/api/listings?*", (route) => {
    const query = Object.fromEntries(new URL(route.request().url()).searchParams);
    requests.push(query);
    const offset = Number(query.offset || 0);
    const listings = Array.from({ length: 48 }, (_, index) => ({
      id: index === 30 ? Number(ids[0]) : index === 0 ? Number(ids[1]) : 1000 + index,
      title: `Квартира ${index + 1}`,
      city: "Київ", district: "Дніпровський", price: 5600000 - index,
      rooms: 2, area: 64, property_type: "apartment", status: "published", images: [],
    })).slice(offset, offset + 24);
    return route.fulfill({ json: { listings, total: 48, has_more: offset === 0, facets: { cities: ["Київ"] } } });
  });
  return requests;
}

async function openFromCatalog(page, url = "/app?source=ua-dim-app&sort=test#results") {
  await page.goto(url);
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(24);
  await page.getByRole("searchbox", { name: "Де шукаєте житло?" }).fill("Дніпровський");
  const searchResponse = page.waitForResponse((response) =>
    response.url().includes("/api/listings?") &&
    new URL(response.url()).searchParams.get("search") === "Дніпровський");
  await page.getByRole("button", { name: "Знайти житло" }).click();
  await searchResponse;
  await expect(page.locator("#results")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("button", { name: "Показати ще", exact: true }).click();
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(48);
  const link = page.locator(`[data-role="listing-card"] a[href="/listing/${ids[0]}"]`).filter({ hasText: "Переглянути" });
  await link.scrollIntoViewIfNeeded();
  await link.focus();
  const y = await page.evaluate(() => scrollY);
  const catalogUrl = page.url();
  await link.press("Enter");
  await expect(page.getByRole("button", { name: "Назад", exact: true })).toBeVisible();
  return { y, catalogUrl };
}

async function expectRestored(page, { y, catalogUrl }) {
  await expect(page).toHaveURL(catalogUrl);
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(48);
  await expect(page.locator(`[data-role="listing-card"] a[href="/listing/${ids[0]}"]`).filter({ hasText: "Переглянути" })).toBeFocused();
  await expect.poll(() => page.evaluate(() => scrollY)).toBeCloseTo(y, 0);
  await expect(page.getByRole("searchbox", { name: "Де шукаєте житло?" })).toHaveValue("Дніпровський");
}

test("listing Назад restores the originating entry, loaded pages, search, scroll and keyboard focus after reload", async ({ page }) => {
  const requests = await setup(page);
  const origin = await openFromCatalog(page);
  await page.reload();
  // A different tab's preferences must not replace this history entry's search.
  await page.evaluate(() => {
    localStorage.setItem("re.keywordSearch", "Львів");
    localStorage.setItem("re.sortBy", "price-asc");
  });
  const back = page.getByRole("button", { name: "Назад", exact: true });
  await back.focus();
  await back.press("Space");
  await expectRestored(page, origin);
  expect(requests.at(-1)).toMatchObject({
    search: "Дніпровський", sort: "price-desc", offset: "24", city: "Київ", minRooms: "2", minPrice: "50000",
  });
});

test("browser Back and repeated listing visits restore the catalog without accumulating return state", async ({ page }) => {
  await setup(page);
  const origin = await openFromCatalog(page, "/real-estate-demo.html?query=retained");
  await page.goBack();
  await expectRestored(page, origin);
  await page.locator(`[data-role="listing-card"] a[href="/listing/${ids[0]}"]`).filter({ hasText: "Переглянути" }).press("Enter");
  await page.getByRole("button", { name: "Назад", exact: true }).click();
  await expectRestored(page, origin);
});

test("recommendations and contact fragment history return to the same catalog, including native back script", async ({ page }) => {
  await setup(page);
  const origin = await openFromCatalog(page);
  await page.locator(`a.recommendation-card[href$="/listing/${ids[1]}"]`).click();
  await page.getByRole("link", { name: "Запитати про об’єкт" }).click();
  await expect(page).toHaveURL(/#contact$/);
  await page.goBack();
  await expect(page).not.toHaveURL(/#contact$/);
  await page.goForward();
  await expect(page).toHaveURL(/#contact$/);
  await expect(page.getByRole("button", { name: "Назад", exact: true })).toBeInViewport();
  await page.evaluate(nativeBackScript);
  await expectRestored(page, origin);
});

test("direct, external and stale-state entry goes to the catalog, never to the external previous page", async ({ page }) => {
  await setup(page);
  await page.route("https://outside.example/**", (route) => route.fulfill({ contentType: "text/html", body: "<h1>External</h1>" }));
  await page.goto("https://outside.example/");
  await page.goto(`/listing/${ids[0]}`);
  await page.reload();
  await page.getByRole("button", { name: "Назад", exact: true }).click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/app");
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(24);
  await page.goto(`/listing/${ids[0]}`);
  await page.evaluate(nativeBackScript);
  await expect(page).toHaveURL("http://127.0.0.1:4173/app");
});

test("new-tab listing has no catalog back provenance", async ({ page }) => {
  await setup(page);
  await page.goto("/app");
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(24);
  const link = page.locator(`[data-role="listing-card"] a[href="/listing/${ids[1]}"]`).filter({ hasText: "Переглянути" });
  await link.evaluate((element) => { element.target = "_blank"; });
  const popup = page.waitForEvent("popup");
  await link.click();
  const tab = await popup;
  await setup(tab);
  await expect(tab.getByRole("button", { name: "Назад", exact: true })).toBeVisible();
  expect(await tab.evaluate(() => history.state?.["uaDim.listingReturn"])).toBeUndefined();
  await tab.getByRole("button", { name: "Назад", exact: true }).click();
  await expect(tab).toHaveURL("http://127.0.0.1:4173/app");
  await tab.close();
});

test("changed search after returning creates a fresh entry snapshot", async ({ page }) => {
  const requests = await setup(page);
  await openFromCatalog(page);
  await page.getByRole("button", { name: "Назад", exact: true }).click();
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(48);
  const input = page.getByRole("searchbox", { name: "Де шукаєте житло?" });
  await input.fill("Оболонь");
  const response = page.waitForResponse((item) =>
    item.url().includes("/api/listings?") && new URL(item.url()).searchParams.get("search") === "Оболонь");
  await page.getByRole("button", { name: "Знайти житло" }).click();
  await response;
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(24);
  await page.getByRole("button", { name: "Показати ще", exact: true }).click();
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(48);
  await page.locator(`[data-role="listing-card"] a[href="/listing/${ids[0]}"]`).filter({ hasText: "Переглянути" }).click();
  await page.getByRole("button", { name: "Назад", exact: true }).click();
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(48);
  await expect(input).toHaveValue("Оболонь");
  expect(requests.at(-1).search).toBe("Оболонь");
});

test("native fallback works on an older listing page without the shared handler", async ({ page }) => {
  await setup(page);
  await page.goto(`/listing/${ids[0]}`);
  await page.evaluate(() => { delete window.uaListingBack; });
  await page.evaluate(nativeBackScript);
  await expect(page).toHaveURL("http://127.0.0.1:4173/app");
});

test("directly reopening the same listing discards inherited catalog return state", async ({ page }) => {
  await setup(page);
  await openFromCatalog(page);
  await page.goto(page.url());
  expect(await page.evaluate(() => performance.getEntriesByType("navigation")[0].type)).toBe("navigate");
  expect(await page.evaluate(() => history.state?.["uaDim.listingReturn"] ?? null)).toBeNull();
  await page.getByRole("button", { name: "Назад", exact: true }).click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/app");
});

test("smart search returns to its own six-result preview, query, scroll and focused link", async ({ page }) => {
  await setup(page);
  await page.goto("/smart-search.html?source=search");
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(6);
  const input = page.getByRole("textbox", { name: "Ключові слова" });
  await input.fill("метро");
  const response = page.waitForResponse((item) =>
    item.url().includes("/api/listings?") && new URL(item.url()).searchParams.get("search") === "метро");
  await page.getByRole("button", { name: "Шукати", exact: true }).click();
  await response;
  const link = page.locator(`[data-role="listing-card"] a[href="/listing/${ids[1]}"]`).filter({ hasText: "Переглянути" });
  await link.scrollIntoViewIfNeeded();
  await link.focus();
  const y = await page.evaluate(() => scrollY);
  await link.press("Enter");
  await page.getByRole("button", { name: "Назад", exact: true }).click();
  await expect(page).toHaveURL("http://127.0.0.1:4173/smart-search.html?source=search");
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(6);
  await expect(link).toBeFocused();
  await expect(input).toHaveValue("метро");
  await expect.poll(() => page.evaluate(() => scrollY)).toBeCloseTo(y, 0);
});
