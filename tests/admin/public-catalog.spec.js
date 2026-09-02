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
