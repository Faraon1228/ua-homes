const { test, expect } = require("@playwright/test");

const heroSelector = '[data-role="homepage-hero"]';
const artSelector = ".homepage-house-art";

test.use({ serviceWorkers: "block" });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "uaDim.privacyConsent.v1",
      JSON.stringify({ version: 1, analytics: false, updatedAt: new Date().toISOString() }),
    );
  });
  await page.route("**/api/listings?*", (route) =>
    route.fulfill({
      json: { listings: [], total: 0, has_more: false, facets: { cities: [] } },
    }),
  );
});

async function openHomepage(page, url = "/real-estate-demo.html") {
  await page.goto(url);
  await expect(page.locator(`${artSelector} img`)).toHaveCount(2);
  await expect.poll(() => page.locator(`${artSelector} img`).evaluateAll(
    (images) => images.every((image) => image.complete && image.naturalWidth > 0),
  )).toBe(true);
}

test("approved skyline loads once behind the unchanged hero content", async ({ page }) => {
  const assets = [];
  page.on("response", (response) => {
    if (response.url().includes("/images/silver-silhouette.svg")) assets.push(response);
  });
  await openHomepage(page);
  expect(assets).toHaveLength(1);
  expect(assets[0].status()).toBe(200);
  expect(assets[0].headers()["content-type"]).toContain("image/svg+xml");

  const hero = page.locator(heroSelector);
  await expect(hero).toHaveCSS("isolation", "isolate");
  await expect(hero).toHaveCSS("overflow", "hidden");
  await expect(hero.locator(":scope > .mx-auto")).toHaveCSS("z-index", "1");
  for (const [index, clip] of ["inset(0px 50% 0px 0px)", "inset(0px 0px 0px 50%)"].entries()) {
    const art = page.locator(artSelector).nth(index);
    await expect(art).toHaveCSS("z-index", "-1");
    await expect(art).toHaveCSS("pointer-events", "none");
    await expect(art).toHaveCSS("clip-path", clip);
    await expect(art).toHaveAttribute("aria-hidden", "true");
    await expect(art.locator("img")).toHaveAttribute("alt", "");
    await expect(art.locator("img")).toHaveAttribute("draggable", "false");
    const narrow = page.viewportSize().width <= 640;
    await expect(art.locator("img")).toHaveCSS("object-fit", narrow ? "contain" : "cover");
    await expect(art.locator("img")).toHaveCSS("object-position", "50% 100%");
    await expect(art.locator("img")).toHaveCSS("opacity", narrow ? "0.3" : "0.32");
  }
  await expect(hero.getByRole("img")).toHaveCount(1);
  await expect(hero.getByRole("img")).toHaveAccessibleName("Логотип UA-Dim");
  await expect(page.locator("#homepage-title")).toHaveText("Знайдіть житло в Україні");
  await expect(page.locator("#homepage-title")).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(page.locator("#header-brand-link")).toHaveAttribute("href", "/real-estate-demo.html");
  await expect(page.locator("#header-auth-cta")).toHaveAttribute("href", "/real-estate-demo.html?seller=1");
  const background = await hero.evaluate((element) => getComputedStyle(element).backgroundImage);
  expect(background).toContain("rgba(37, 99, 235, 0.28)");
  expect(background).toMatch(/linear-gradient\(145deg, rgb\(15, 23, 42\)(?: 0%)?, rgb\(30, 58, 138\) 52%, rgb\(15, 118, 110\)(?: 100%)?\)/);

  const button = hero.getByRole("button", { name: "Знайти житло" });
  expect(await button.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
  })).toBe(true);
});

test("left then right reveal has exact timing and ends without looping", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await openHomepage(page);
  const timeline = await page.locator(artSelector).evaluateAll((elements) => {
    const animations = elements.map((element) => element.getAnimations()[0]);
    const timings = animations.map((animation, index) => {
      animation.pause();
      const { delay, duration, iterations, fill } = animation.effect.getTiming();
      const easing = getComputedStyle(elements[index]).animationTimingFunction;
      return { delay, duration, iterations, easing, fill };
    });
    const frames = [50, 550, 1025, 1500, 1950, 3000].map((time) => {
      animations.forEach((animation) => { animation.currentTime = time; });
      return elements.map((element) => {
        const style = getComputedStyle(element);
        return { opacity: Number(style.opacity), x: new DOMMatrixReadOnly(style.transform).m41 };
      });
    });
    return { timings, frames };
  });
  expect(timeline.timings).toEqual([100, 1050].map((delay) => ({
    delay, duration: 900, iterations: 1, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "both",
  })));
  const entry = page.viewportSize().width <= 640 ? 24 : 48;
  expect(timeline.frames[0]).toEqual([{ opacity: 0, x: -entry }, { opacity: 0, x: entry }]);
  expect(timeline.frames[1][0].opacity).toBeGreaterThan(0);
  expect(timeline.frames[1][0].opacity).toBeLessThan(1);
  expect(timeline.frames[1][1]).toEqual({ opacity: 0, x: entry });
  expect(timeline.frames[2]).toEqual([{ opacity: 1, x: 0 }, { opacity: 0, x: entry }]);
  expect(timeline.frames[3][0]).toEqual({ opacity: 1, x: 0 });
  expect(timeline.frames[3][1].opacity).toBeGreaterThan(0);
  expect(timeline.frames[3][1].opacity).toBeLessThan(1);
  for (const frame of timeline.frames.slice(4)) {
    expect(frame).toEqual([{ opacity: 1, x: 0 }, { opacity: 1, x: 0 }]);
  }
});

test("keyboard search reaches the API without restarting the decoration", async ({ page, browserName }) => {
  const searches = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/listings") searches.push(url.searchParams.get("search"));
  });
  await openHomepage(page);
  await page.evaluate(() => {
    window.originalHouseAnimations = [...document.querySelectorAll(".homepage-house-art")]
      .map((element) => element.getAnimations()[0]);
  });
  await page.getByRole("searchbox", { name: "Де шукаєте житло?" }).fill("Печерськ");
  // Safari's default keyboard policy skips buttons when full keyboard access is off.
  if (browserName === "chromium") {
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Знайти житло" })).toBeFocused();
  }
  await page.keyboard.press("Enter");
  await expect.poll(() => searches.includes("Печерськ")).toBe(true);
  await expect(page.locator("#results")).toBeFocused();
  expect(await page.evaluate(() =>
    [...document.querySelectorAll(".homepage-house-art")].every(
      (element, index) => element.getAnimations()[0] === window.originalHouseAnimations[index],
    ),
  )).toBe(true);
});

test("reduced motion shows both halves immediately, without delayed animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openHomepage(page);
  for (const art of await page.locator(artSelector).all()) {
    await expect(art).toHaveCSS("animation-name", "none");
    await expect(art).toHaveCSS("transform", "none");
    await expect(art).toHaveCSS("opacity", "1");
    expect(await art.evaluate((element) => element.getAnimations().length)).toBe(0);
  }
});

test("narrow mobile keeps the skyline aspect ratio and original layout", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openHomepage(page);
  const geometry = await page.evaluate(() => {
    const selectors = ["header", '[data-role="homepage-hero"]', "#homepage-title", "#hero-property-form"];
    const measure = () => selectors.map((selector) =>
      document.querySelector(selector).getBoundingClientRect().toJSON());
    const before = measure();
    document.querySelectorAll(".homepage-house-art").forEach((element) => { element.hidden = true; });
    const after = measure();
    document.querySelectorAll(".homepage-house-art").forEach((element) => { element.hidden = false; });
    return { before, after, width: document.documentElement.scrollWidth, viewport: innerWidth };
  });
  expect(geometry.before).toEqual(geometry.after);
  expect(geometry.width).toBeLessThanOrEqual(geometry.viewport);
  for (const image of await page.locator(`${artSelector} img`).all()) {
    await expect(image).toHaveCSS("object-fit", "contain");
    await expect(image).toHaveCSS("object-position", "50% 100%");
    await expect(image).toHaveAttribute("width", "1600");
    await expect(image).toHaveAttribute("height", "900");
  }
});

test("the app route shares the hero and both seller routes keep it hidden", async ({ page }) => {
  // Python's static test server does not apply the production Netlify rewrites.
  await page.route(/\/(app|seller)(\?.*)?$/, async (route) => {
    const response = await route.fetch({ url: "http://127.0.0.1:4173/real-estate-demo.html" });
    await route.fulfill({ response });
  });
  await openHomepage(page, "/app?source=ua-dim-app&release=20260820-photo-library");
  await expect(page.locator(heroSelector)).toBeVisible();
  for (const url of ["/seller", "/real-estate-demo.html?seller=1"]) {
    await page.goto(url);
    await expect(page.locator("html")).toHaveClass(/seller-page/);
    await expect(page.locator(heroSelector)).toBeHidden();
    await expect(page.locator(artSelector).first()).toBeHidden();
    await expect(page.locator(artSelector).last()).toBeHidden();
    await expect(page.locator("#header-brand-link")).toBeVisible();
  }
});
