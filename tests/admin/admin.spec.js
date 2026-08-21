const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

const moderator = {
  id: 2,
  name: "Марія Модератор",
  email: "moderator@example.test",
  role: "moderator",
  permissions: [
    "audit/read",
    "dashboard/read",
    "listings/moderate",
    "listings/read",
    "reports/manage",
    "verifications/manage",
  ],
};

const admin = {
  id: 1,
  name: "Олена Адміністратор",
  email: "admin@example.test",
  role: "admin",
  permissions: [
    "admin/all",
    "agencies/manage",
    "audit/read",
    "dashboard/read",
    "leads/manage",
    "listings/moderate",
    "listings/read",
    "listings/write",
    "reports/manage",
    "system/read",
    "users/manage",
    "verifications/manage",
  ],
};

const overview = {
  total_listings: 1284,
  published_listings: 1102,
  total_users: 368,
  total_agents: 24,
  avg_price: 4120000,
  backlog: { moderation: 12, verifications: 4, reports: 1 },
  by_city: [{ city: "Київ", count: 540 }],
  recent_listings: [
    {
      id: 42,
      title: "Квартира біля Дніпра",
      city: "Київ",
      price: 5600000,
      created_at: "2026-08-21 08:00:00",
    },
  ],
};

async function mockSessionAndOverview(page, staff = moderator) {
  await page.route("**/api/admin/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "csrf_token_for_browser_tests_123456", staff }),
    }),
  );
  await page.route("**/api/admin/dashboard/stats?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overview),
    }),
  );
}

test("login handles failure and succeeds without browser token storage", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/admin/auth/session", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: "Unauthorized" }),
    }),
  );
  await page.route("**/api/admin/auth/login", async (route) => {
    attempts += 1;
    const request = route.request();
    expect(request.headers().authorization).toBeUndefined();
    expect(request.postDataJSON()).toEqual({
      email: "moderator@example.test",
      password: "correct-password",
    });
    await route.fulfill({
      status: attempts === 1 ? 401 : 200,
      contentType: "application/json",
      body: JSON.stringify(
        attempts === 1
          ? { error: "Invalid credentials" }
          : {
              ok: true,
              csrf_token: "csrf_token_for_browser_tests_123456",
              staff: moderator,
            },
      ),
    });
  });

  await page.goto("/admin/login.html");
  await page.getByTestId("login-email-input").fill("moderator@example.test");
  await page.getByTestId("login-password-input").fill("correct-password");
  await page.getByTestId("login-submit-button").click();
  await expect(page.getByTestId("login-status")).toHaveAttribute("data-tone", "error");
  await expect(page.getByTestId("login-status")).toContainText("Invalid credentials");

  await page.getByTestId("login-submit-button").click();
  await expect(page.getByTestId("login-status")).toHaveAttribute("data-tone", "success");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("admin_token")))
    .toBeNull();
});

test("session loading failure can be retried without losing the shell", async ({ page }) => {
  let sessionRequests = 0;
  let releaseFirstRequest;
  const firstRequestBlocked = new Promise((resolve) => {
    releaseFirstRequest = resolve;
  });
  await page.route("**/api/admin/auth/session", async (route) => {
    sessionRequests += 1;
    if (sessionRequests === 1) {
      await firstRequestBlocked;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "Сесійний сервіс недоступний" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        csrf_token: "csrf_token_for_browser_tests_123456",
        staff: moderator,
      }),
    });
  });
  await page.route("**/api/admin/dashboard/stats?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overview),
    }),
  );

  await page.goto("/admin/dashboard.html");
  await expect(page.getByTestId("session-loading")).toBeVisible();
  releaseFirstRequest();
  await expect(page.getByTestId("session-error")).toBeVisible();
  await page.getByTestId("error-retry-button").click();
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(
    page.getByTestId("main-content").getByRole("heading", { name: "Огляд" }),
  ).toBeVisible();
});

test("expired staff session redirects to login", async ({ page }) => {
  await page.route("**/api/admin/auth/session", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ error: "Unauthorized" }),
    }),
  );

  await page.goto("/admin/dashboard.html");
  await expect(page).toHaveURL(/\/admin\/login\.html$/);
  await expect(page.getByTestId("login-page")).toBeVisible();
});

test("moderator sees only permitted navigation and an accessible overview", async ({ page }) => {
  await mockSessionAndOverview(page);
  await page.goto("/admin/dashboard.html");

  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByTestId("nav-item-moderation")).toBeVisible();
  await expect(page.getByTestId("nav-item-audit")).toBeVisible();
  await expect(page.getByTestId("nav-item-users")).toHaveCount(0);
  await expect(page.getByTestId("nav-item-agencies")).toHaveCount(0);
  await expect(page.getByTestId("nav-item-health")).toHaveCount(0);
  await expect(
    page.getByTestId("main-content").getByRole("heading", { name: "Огляд" }),
  ).toBeVisible();

  const results = await new AxeBuilder({ page }).include("#main-content").analyze();
  expect(results.violations).toEqual([]);
});

test("administrator sees privileged operational sections", async ({ page }) => {
  await mockSessionAndOverview(page, admin);
  await page.goto("/admin/dashboard.html");

  for (const item of ["requests", "users", "agencies", "analytics", "health"]) {
    await expect(page.getByTestId(`nav-item-${item}`)).toBeVisible();
  }
  await expect(
    page.getByTestId("main-content").getByRole("heading", { name: "Огляд" }),
  ).toBeVisible();
});

test("moderation exposes retry state and protects reasoned actions with CSRF", async ({ page }) => {
  await mockSessionAndOverview(page);
  let queueRequests = 0;
  const moderationRequests = [];

  await page.route("**/api/admin/moderation/queue?*", async (route) => {
    queueRequests += 1;
    if (queueRequests === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "Тимчасово недоступно" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 1,
        limit: 20,
        offset: 0,
        queue: [
          {
            id: 42,
            title: "Квартира біля Дніпра",
            city: "Київ",
            district: "Дніпровський",
            price: 5600000,
            status: "pending",
            moderation_status: "pending_review",
            created_at: "2026-08-21 08:00:00",
          },
        ],
      }),
    });
  });
  await page.route("**/api/admin/listings/42/moderate", async (route) => {
    moderationRequests.push({
      headers: route.request().headers(),
      body: route.request().postDataJSON(),
    });
    await route.fulfill({
      status: moderationRequests.length === 1 ? 503 : 200,
      contentType: "application/json",
      body: JSON.stringify(
        moderationRequests.length === 1
          ? { error: "Сервіс модерації недоступний" }
          : { ok: true, status: "rejected" },
      ),
    });
  });

  await page.goto("/admin/dashboard.html#/moderation");
  await expect(page.getByTestId("moderation-queue-error")).toBeVisible();
  await page.getByTestId("error-retry-button").click();
  await expect(page.getByTestId("moderation-reject-42")).toBeVisible();
  await page.getByTestId("moderation-queue-table-select-42").check();
  await expect(page.getByTestId("moderation-bulk-approve")).toBeVisible();
  await page.getByTestId("moderation-search-input").fill("Дніпро");
  await expect(page.getByTestId("moderation-bulk-approve")).toHaveCount(0);
  await page.getByTestId("moderation-search-input").fill("");
  await page.getByTestId("moderation-reject-42").click();

  const dialog = page.getByTestId("moderation-action-dialog");
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("moderation-action-reason")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("moderation-action-cancel")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("moderation-action-reason")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("moderation-reject-42")).toBeFocused();

  await page.getByTestId("moderation-reject-42").click();
  await expect(page.getByTestId("moderation-action-confirm")).toBeDisabled();
  await page.getByTestId("moderation-action-reason").fill("Підозрілий опис оголошення");
  await page.getByTestId("moderation-action-confirm").click();
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Сервіс модерації недоступний" })).toBeVisible();
  await page.getByTestId("moderation-action-confirm").click();

  await expect.poll(() => moderationRequests.length).toBe(2);
  expect(moderationRequests[1].headers["x-csrf-token"]).toBe(
    "csrf_token_for_browser_tests_123456",
  );
  expect(moderationRequests[1].body).toEqual({
    action: "reject",
    reason: "Підозрілий опис оголошення",
  });
  await expect(dialog).toHaveCount(0);
});

test("listing verification actions update the matching trust field", async ({ page }) => {
  await mockSessionAndOverview(page);
  let verificationUpdate = null;
  await page.route("**/api/admin/moderation/queue?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ total: 0, limit: 20, offset: 0, queue: [] }),
    }),
  );
  await page.route("**/api/admin/verifications?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 1,
        limit: 20,
        offset: 0,
        verifications: [
          {
            id: 42,
            title: "Квартира біля Дніпра",
            city: "Київ",
            listing_verification_status: "pending",
            owner_verification_status: "verified",
            phone_verification_status: "verified",
            created_at: "2026-08-21 08:00:00",
          },
        ],
      }),
    }),
  );
  await page.route("**/api/admin/verifications/42", async (route) => {
    verificationUpdate = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, listing_verification_status: "verified" }),
    });
  });

  await page.goto("/admin/dashboard.html#/moderation");
  await page.getByRole("tab", { name: "Верифікації" }).click();
  await page.getByRole("button", { name: "Підтвердити оголошення" }).click();
  await expect.poll(() => verificationUpdate).toEqual({
    listing_verification_status: "verified",
  });
});

test("lead response draft resets when another lead opens", async ({ page }) => {
  await mockSessionAndOverview(page, admin);
  await page.route("**/api/admin/leads?*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 2,
        limit: 20,
        offset: 0,
        leads: [
          {
            id: 1,
            name: "Покупець А",
            source: "listing_page",
            status: "new",
            response_message: "",
            created_at: "2026-08-21 08:00:00",
          },
          {
            id: 2,
            name: "Покупець Б",
            source: "listing_page",
            status: "new",
            response_message: "Чернетка Б",
            created_at: "2026-08-21 08:01:00",
          },
        ],
      }),
    }),
  );

  await page.goto("/admin/dashboard.html#/requests");
  await page.getByRole("button", { name: "Покупець А" }).click();
  await page.getByLabel("Відповідь").fill("Чернетка А");
  await page.getByRole("button", { name: "Закрити панель" }).click();
  await page.getByRole("button", { name: "Покупець Б" }).click();
  await expect(page.getByLabel("Відповідь")).toHaveValue("Чернетка Б");
});

test("mobile navigation opens, closes, and does not overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium");
  await mockSessionAndOverview(page);
  await page.goto("/admin/dashboard.html");

  await expect(page.getByTestId("primary-nav")).toHaveAttribute("data-state", "closed");
  await page.getByTestId("mobile-nav-toggle").click();
  await expect(page.getByTestId("primary-nav")).toHaveAttribute("data-state", "open");
  await page.getByTestId("mobile-nav-scrim").click();
  await expect(page.getByTestId("primary-nav")).toHaveAttribute("data-state", "closed");

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
