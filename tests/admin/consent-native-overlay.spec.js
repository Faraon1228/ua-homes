const { test, expect } = require("@playwright/test");

test.use({ serviceWorkers: "block" });

// Native Flutter FABs: 40px, right 16; bottom 16 (picker) or 80 (share, stacked above picker).
const FAB = { size: 40, right: 16, pickerBottom: 16, shareBottom: 80 };

test.beforeEach(async ({ page }) => {
  await page.route("**/api/listings?*", (route) =>
    route.fulfill({ json: { listings: [], total: 0, has_more: false, facets: { cities: [] } } }),
  );
});

async function bannerRect(page, url, { native }) {
  if (native) {
    await page.addInitScript(() => {
      window.webkit = { messageHandlers: { UaDimMediaPicker: { postMessage() {} } } };
    });
  }
  await page.goto(url);
  const banner = page.locator("#ua-privacy-banner");
  await expect(banner).toBeVisible();
  const allow = banner.getByRole("button").first();
  await expect(allow).toBeVisible();
  return page.evaluate(() => {
    const b = document.getElementById("ua-privacy-banner").getBoundingClientRect();
    return { top: b.top, bottom: b.bottom, height: b.height, vh: innerHeight, vw: innerWidth };
  });
}

function fabTop(vh, bottom) {
  return vh - bottom - FAB.size;
}

test("plain web consent banner keeps its original position", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 700 });
  const r = await bannerRect(page, "/real-estate-demo.html", { native: false });
  expect(r.vh - r.bottom).toBeLessThanOrEqual(17);
});

test("app consent banner clears the native photo button", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 700 });
  const web = await bannerRect(page, "/real-estate-demo.html", { native: false });
  const page2 = await page.context().newPage();
  await page2.setViewportSize({ width: 390, height: 700 });
  await page2.route("**/api/listings?*", (route) =>
    route.fulfill({ json: { listings: [], total: 0, has_more: false, facets: { cities: [] } } }),
  );
  const app = await bannerRect(page2, "/real-estate-demo.html", { native: true });
  expect(app.bottom).toBeLessThan(web.bottom);
  expect(app.bottom).toBeLessThanOrEqual(fabTop(app.vh, FAB.pickerBottom));
});

test("app consent on a listing path clears both stacked native buttons and stays reachable at narrow width", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.route(/\/listing\/demo-1$/, async (route) => {
    const response = await route.fetch({ url: "http://127.0.0.1:4173/real-estate-demo.html" });
    const body = (await response.text()).replace("<head>", '<head><base href="/">');
    await route.fulfill({ response, body });
  });
  const app = await bannerRect(page, "/listing/demo-1", { native: true });
  expect(app.bottom).toBeLessThanOrEqual(fabTop(app.vh, FAB.shareBottom));
  expect(app.top).toBeGreaterThanOrEqual(0);
});
