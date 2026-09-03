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
