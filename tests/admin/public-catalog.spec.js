const { test, expect } = require("@playwright/test");

const listing = {
  id: 42,
  title: "Квартира біля Дніпра",
  city: "Київ",
  district: "Дніпровський",
  price: 5600000,
  rooms: 2,
  area: 64,
  property_type: "apartment",
  status: "published",
  images: [],
};

async function mockCatalog(page, handler) {
  await page.route("**/api/listings?*", handler);
}

test("verification badges require matching flags and statuses and explain their limits", async ({ page }) => {
  await mockCatalog(page, (route) => route.fulfill({ json: {
    listings: [
      { ...listing, id: 71, title: "Непогоджена перевірка", verified_owner: true, owner_verification_status: "pending", verified_listing: true, listing_verification_status: "pending" },
      { ...listing, id: 72, title: "Підтверджена перевірка", verified_owner: true, owner_verification_status: "verified", verified_listing: true, listing_verification_status: "verified" },
    ],
    total: 2, has_more: false,
  } }));
  await page.route("**/api/listings/72/trust", (route) => route.fulfill({ json: {
    listing_verification_status: "verified", verified_listing: true, history: [],
  } }));
  await page.goto("/real-estate-demo.html");
  const pending = page.locator('[data-role="listing-card"]').filter({ hasText: "Непогоджена перевірка" });
  const verified = page.locator('[data-role="listing-card"]').filter({ hasText: "Підтверджена перевірка" });
  await expect(pending).not.toContainText("✓ Власник:");
  await expect(pending).not.toContainText("✓ Перевірене оголошення");
  await expect(verified).toContainText("✓ Власник: перевірку пройдено");
  await expect(verified).toContainText("✓ Перевірене оголошення");
  await verified.getByRole("button", { name: "Довіра й безпека", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("не гарантують стан житла");
});

test("offer switch filters sale and rent, preserves search, resets paging and survives reload", async ({ page }) => {
  const requests = [];
  const rent = { ...listing, id: 43, title: "Оренда біля Дніпра", listing_type: "rent", price: 700 };
  const sale = { ...listing, listing_type: "sale" };
  await mockCatalog(page, (route) => {
    const query = Object.fromEntries(new URL(route.request().url()).searchParams);
    requests.push(query);
    const listings = query.listing_type === "rent" ? [rent] : query.listing_type === "sale" ? [sale] : [sale, rent];
    return route.fulfill({ json: { listings, total: listings.length, has_more: false } });
  });
  await page.goto("/real-estate-demo.html");
  const offers = page.getByRole("group", { name: "Тип пропозиції", exact: true });
  await expect(offers.getByRole("button", { name: "Усі", exact: true })).toHaveCount(0);
  await expect(offers.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(2);
  expect(requests[0].listing_type).toBeUndefined();
  await page.getByRole("searchbox", { name: "Де шукаєте житло?" }).fill("Дніпра");
  await page.getByRole("button", { name: "Знайти житло", exact: true }).click();
  await expect.poll(() => requests.at(-1)?.search).toBe("Дніпра");
  await offers.getByRole("button", { name: "Орендувати", exact: true }).click();
  await expect.poll(() => requests.at(-1)).toMatchObject({ listing_type: "rent", search: "Дніпра", offset: "0" });
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(1);
  await expect(page.locator('[data-role="listing-card"]')).toContainText("/міс.");
  await expect(page).toHaveURL(/listingType=rent/);
  await page.reload();
  await expect(offers.getByRole("button", { name: "Орендувати", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-role="listing-card"]')).toContainText(rent.title);
  await offers.getByRole("button", { name: "Купити", exact: true }).click();
  await expect.poll(() => requests.at(-1)).toMatchObject({ listing_type: "sale", search: "Дніпра", offset: "0" });
  await expect(page.locator('[data-role="listing-card"]')).not.toContainText("/міс.");
  const removeSale = page.getByRole("button", { name: "Прибрати фільтр Продаж", exact: true });
  if (!(await removeSale.isVisible())) await page.getByRole("button", { name: "Розширені фільтри", exact: false }).click();
  await removeSale.click();
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(2);
  expect(requests.at(-1).listing_type).toBeUndefined();
  expect(new URL(page.url()).searchParams.has("listingType")).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
});

test("rent deep link overrides stored sale and rent filtering applies to map and saved searches", async ({ page }) => {
  const rent = { ...listing, listing_type: "rent", price: 700, latitude: 50.45, longitude: 30.52 };
  const requests = [];
  await page.addInitScript(() => localStorage.setItem("re.listingTypeFilter", "sale"));
  await mockCatalog(page, (route) => {
    requests.push(Object.fromEntries(new URL(route.request().url()).searchParams));
    return route.fulfill({ json: { listings: [rent], total: 1, has_more: false } });
  });
  await page.goto("/real-estate-demo.html?listingType=rent");
  const offers = page.getByRole("group", { name: "Тип пропозиції", exact: true });
  await expect(offers.getByRole("button", { name: "Орендувати", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-role="listing-card"]')).toHaveCount(1);
  await page.getByRole("button", { name: "Карта", exact: true }).click();
  await expect(page.locator("#listings-map .leaflet-marker-icon")).toHaveCount(1);
  await page.locator("#listings-map .leaflet-marker-icon").click();
  await expect(page.locator("#listings-map .leaflet-popup-content")).toContainText("/міс.");
  const save = page.getByRole("button", { name: "Зберегти запит", exact: true });
  if (!(await save.isVisible())) await page.getByRole("button", { name: "Розширені фільтри", exact: false }).click();
  page.once("dialog", (dialog) => dialog.accept("Оренда тест"));
  await save.click();
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("re.savedSearches") || "[]")[0]?.filters?.listingTypeFilter)).toBe("rent");
  await page.getByRole("button", { name: "Прибрати фільтр Оренда", exact: true }).click();
  await expect(offers.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect.poll(() => requests.at(-1)?.listing_type ?? "").toBe("");
  await page.getByRole("button", { name: "Оренда тест", exact: true }).click();
  await expect(offers.getByRole("button", { name: "Орендувати", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => requests.at(-1)?.listing_type).toBe("rent");
  await page.locator("#search").getByRole("button", { name: "Скинути фільтри", exact: true }).click();
  await expect(offers.locator('[aria-pressed="true"]')).toHaveCount(0);
  await expect.poll(() => requests.at(-1)?.listing_type ?? "").toBe("");
});

test("sell action opens the seller cabinet rather than filtering listings", async ({ page }) => {
  await mockCatalog(page, (route) => route.fulfill({ json: { listings: [], total: 0, has_more: false } }));
  await page.goto("/real-estate-demo.html?listingType=rent");
  const offers = page.getByRole("group", { name: "Тип пропозиції", exact: true });
  await expect(offers.locator("button, a")).toHaveText(["Купити", "Продати", "Орендувати"]);
  const sell = offers.getByRole("link", { name: "Продати", exact: true });
  await expect(sell).toHaveAttribute("href", "/real-estate-demo.html?seller=1");
  await sell.click();
  await expect(page).toHaveURL(/seller=1/);
  await expect(page.locator("html")).toHaveClass(/seller-page/);
  await expect(page.getByRole("group", { name: "Тип пропозиції", exact: true })).toHaveCount(0);
});

test("premium and marketplace loaders remain active as self-hosted scripts", async ({
  page,
}) => {
  await page.addInitScript(() => {
    class ImmediateIntersectionObserver {
      constructor(callback) {
        this.callback = callback;
      }
      observe() {
        this.callback([{ isIntersecting: true }]);
      }
      disconnect() {}
    }
    window.IntersectionObserver = ImmediateIntersectionObserver;
  });
  await mockCatalog(page, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ listings: [], total: 0, has_more: false }),
    }),
  );
  const loadedScripts = [];
  page.on("request", (request) => {
    if (/premium\.js|marketplace-extensions\.js/.test(request.url())) {
      loadedScripts.push(request.url());
    }
  });

  await page.goto("/real-estate-demo.html?payment=return&order_id=smoke-order");
  await expect.poll(() => loadedScripts.some((url) => url.includes("premium.js"))).toBe(true);

  await page.evaluate(() => window.dispatchEvent(new Event("uah:catalog-settled")));
  await expect
    .poll(() => loadedScripts.some((url) => url.includes("marketplace-extensions.js")))
    .toBe(true);

  await page.evaluate(() => window.uaPremium.open());
  await expect(page.locator("#ua-premium-modal")).toBeVisible();
});

test("public catalog loads mocked listings and sends hero search at the API boundary", async ({
  page,
}) => {
  const requests = [];
  await mockCatalog(page, async (route) => {
    const url = new URL(route.request().url());
    requests.push(Object.fromEntries(url.searchParams));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        listings: [listing],
        total: 1,
        has_more: false,
        facets: { cities: ["Київ"] },
      }),
    });
  });

  await page.goto("/real-estate-demo.html");
  await expect(page.getByRole("heading", { name: "Показано 1 з 1" })).toBeVisible();
  await expect(page.locator('[data-role="listing-card"]')).toContainText(
    "Квартира біля Дніпра",
  );

  await page.getByRole("searchbox", { name: "Де шукаєте житло?" }).fill("Печерськ");
  await page.getByRole("button", { name: "Знайти житло" }).click();

  await expect
    .poll(() => requests.find((request) => request.search === "Печерськ"))
    .toMatchObject({
      status: "published",
      search: "Печерськ",
      includeFacets: "1",
    });
  await expect(page.locator("#results")).toBeFocused();
});

test("public catalog filters by Ukrainian region and settlement selector", async ({
  page,
}) => {
  const requests = [];
  await mockCatalog(page, async (route) => {
    const url = new URL(route.request().url());
    requests.push(Object.fromEntries(url.searchParams));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        listings: [{ ...listing, region: "Київська", city: "Буча" }],
        total: 1,
        has_more: false,
        facets: { regions: ["Київська", "Львівська"], cities: ["Буча", "Київ"] },
      }),
    });
  });

  await page.goto("/real-estate-demo.html");
  await expect(page.getByRole("heading", { name: "Показано 1 з 1" })).toBeVisible();
  const regionSelect = page.locator("#filter-region");
  if (!(await regionSelect.isVisible())) {
    await page.getByRole("button", { name: /Фільтри/ }).first().click();
  }
  await expect(regionSelect).toBeVisible();
  await page.locator("#filter-region").selectOption("Київська");

  await expect
    .poll(() => requests.find((r) => r.region === "Київська"))
    .toMatchObject({
      status: "published",
      region: "Київська",
    });

  await page.locator("#filter-city").selectOption("Буча");
  await expect
    .poll(() => requests.find((r) => r.region === "Київська" && r.city === "Буча"))
    .toMatchObject({
      status: "published",
      region: "Київська",
      city: "Буча",
    });
});

test("public catalog exposes a deterministic retry path after an API failure", async ({
  page,
}) => {
  let attempts = 0;
  await mockCatalog(page, (route) => {
    attempts += 1;
    return route.fulfill({
      status: attempts === 1 ? 503 : 200,
      contentType: "application/json",
      body: JSON.stringify(
        attempts === 1
          ? { error: "Unavailable" }
          : { listings: [listing], total: 1, has_more: false },
      ),
    });
  });

  await page.goto("/real-estate-demo.html");
  const alert = page.getByRole("alert").filter({ hasText: "Каталог тимчасово недоступний" });
  await expect(alert).toBeVisible();
  await alert.getByRole("button", { name: "Спробувати ще раз" }).click();
  await expect(page.getByRole("heading", { name: "Показано 1 з 1" })).toBeVisible();
  expect(attempts).toBe(2);
});

test("public app clears cached auth when profile refresh returns 401", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("uaDim.authToken", "expired-token");
    localStorage.setItem(
      "uaDim.currentUser",
      JSON.stringify({ id: 7, name: "Тест", email: "test@example.test", account_type: "owner" }),
    );
  });
  await mockCatalog(page, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ listings: [], total: 0, has_more: false }),
    }),
  );
  await page.route("**/api/auth/me", async (route) => {
    expect(route.request().headers().authorization).toBe("Bearer expired-token");
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: "Unauthorized" }),
    });
  });

  await page.goto("/real-estate-demo.html?seller=1");
  await expect(page.getByText("Сесія закінчилась — увійдіть у кабінет знову.")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => ({
        token: localStorage.getItem("uaDim.authToken"),
        user: localStorage.getItem("uaDim.currentUser"),
      })),
    )
    .toEqual({ token: null, user: null });
});

test("seller dashboard shows a red logout action next to catalog navigation", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("uaDim.authToken", "seller-token");
    localStorage.setItem(
      "uaDim.currentUser",
      JSON.stringify({ id: 7, name: "Продавець", email: "seller@example.test", account_type: "owner" }),
    );
  });
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user: { id: 7, name: "Продавець", email: "seller@example.test", account_type: "owner" },
      }),
    }),
  );
  await page.route("**/api/inquiries", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ inquiries: [] }) }),
  );
  await page.route("**/api/listings?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ listings: [], total: 0, has_more: false }),
    }),
  );

  await page.goto("/real-estate-demo.html?seller=1");

  await expect(page.locator("#header-auth-cta")).toHaveAttribute("href", "/real-estate-demo.html");
  const logout = page.locator("#header-logout-cta");
  await expect(logout).toBeVisible();
  await expect(logout).toHaveClass(/bg-rose-600/);

  await logout.click();
  await expect(logout).toHaveCount(0);
  await expect
    .poll(() =>
      page.evaluate(() => ({
        token: localStorage.getItem("uaDim.authToken"),
        user: localStorage.getItem("uaDim.currentUser"),
      })),
    )
    .toEqual({ token: null, user: null });
});

test("seller can delete the account with password, retry after storage failure and is logged out", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("uaDim.authToken", "seller-token");
    localStorage.setItem(
      "uaDim.currentUser",
      JSON.stringify({ id: 7, name: "Продавець", email: "seller@example.test", account_type: "owner" }),
    );
  });
  const json = (route, body, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/auth/me", (route) =>
    json(route, { user: { id: 7, name: "Продавець", email: "seller@example.test", account_type: "owner" } }),
  );
  await page.route("**/api/inquiries", (route) => json(route, { inquiries: [] }));
  await page.route("**/api/listings?*", (route) => json(route, { listings: [], total: 0, has_more: false }));
  const attempts = [];
  await page.route("**/api/auth/delete-account", (route) => {
    attempts.push(route.request().postDataJSON());
    if (attempts.length === 1) {
      return json(route, { error: "Не вдалося видалити медіафайли.", retryable: true }, 502);
    }
    return json(route, { ok: true, deleted: true });
  });

  await page.goto("/real-estate-demo.html?seller=1");
  await page.locator("details", { hasText: "Профіль і тариф" }).locator("summary").click();
  await page.getByRole("button", { name: "Видалити акаунт" }).click();
  const dialog = page.getByRole("dialog", { name: "Видалити акаунт" });
  const submit = dialog.getByRole("button", { name: "Видалити назавжди" });
  await expect(submit).toBeDisabled();
  await dialog.getByLabel("Пароль для підтвердження").fill("secret-pass");
  await dialog.getByRole("checkbox").check();
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("ще не видалено повністю");
  expect(await page.evaluate(() => localStorage.getItem("uaDim.authToken"))).toBe("seller-token");
  await dialog.getByRole("button", { name: "Повторити видалення" }).click();
  await expect(dialog).toHaveCount(0);
  expect(attempts).toEqual([
    { password: "secret-pass", confirm: true },
    { password: "secret-pass", confirm: true },
  ]);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("uaDim.authToken")))
    .toBeNull();
});

test("seller edits stored photos as previews without exposing Cloudinary URLs", async ({ page }) => {
  const firstPhoto = "https://res.cloudinary.com/ua-dim/image/upload/v1/listings/first.jpg";
  const secondPhoto = "https://res.cloudinary.com/ua-dim/image/upload/v1/listings/second.jpg";
  const sellerListing = {
    ...listing,
    district: "Оболонський",
    floor: 4,
    total_floors: 12,
    description: "Світла квартира",
    listing_type: "sale",
    condition_type: "вторинка",
    listing_status: "active",
    images: [firstPhoto, secondPhoto],
  };
  let savedPayload;

  await page.addInitScript(() => {
    localStorage.setItem("uaDim.authToken", "seller-token");
    localStorage.setItem(
      "uaDim.privacyConsent.v1",
      JSON.stringify({ version: 1, analytics: false, updatedAt: "2026-09-03T00:00:00.000Z" }),
    );
    localStorage.setItem(
      "uaDim.currentUser",
      JSON.stringify({ id: 7, name: "Продавець", email: "seller@example.test", account_type: "owner" }),
    );
  });
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user: { id: 7, name: "Продавець", email: "seller@example.test", account_type: "owner" },
      }),
    }),
  );
  await page.route("**/api/inquiries", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ inquiries: [] }) }),
  );
  await page.route("**/api/listings/42", async (route) => {
    savedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ listing: { ...sellerListing, ...savedPayload, status: "published" } }),
    });
  });
  await page.route("**/api/listings?*", (route) => {
    const url = new URL(route.request().url());
    const listings = url.searchParams.get("mine") === "1" ? [sellerListing] : [];
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ listings, total: listings.length, has_more: false }),
    });
  });

  await page.goto("/real-estate-demo.html?seller=1");
  await page.getByRole("button", { name: "Редагувати" }).click();

  const dialog = page.getByRole("dialog", { name: "Профільне оголошення" });
  await expect(dialog.getByRole("img", { name: "Фото оголошення 1" })).toBeVisible();
  await expect(dialog.getByRole("img", { name: "Фото оголошення 2" })).toBeVisible();
  await expect(dialog.locator('input[type="url"]')).toHaveCount(0);
  await expect(dialog.getByText("Посилання на фото", { exact: false })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Додати фото за посиланням" })).toHaveCount(0);

  await dialog.getByRole("button", { name: "Видалити фото 1" }).click();
  await expect(dialog.getByRole("img", { name: "Фото оголошення 1" })).toHaveAttribute(
    "src",
    /second\.jpg/,
  );
  await dialog.getByRole("button", { name: "Зберегти зміни" }).click();

  await expect.poll(() => savedPayload?.images).toEqual([secondPhoto]);
});
