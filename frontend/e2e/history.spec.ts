import { test, expect } from "@playwright/test";

// Phase 14.9 acceptance (plan §2.15): a run started, finished and then
// navigated away from can be reopened at its own URL and shows the same
// ranking it showed when it finished — without re-running anything.

const RESEARCH_ID = "11111111-1111-1111-1111-111111111111";
const QUESTION = "most underrated US states for nature";
const FINISHED =
  "Finished. Every discussion we set out to read was read, so these counts reflect what people actually said.";

const DIAGNOSTICS = {
  source_health: [],
  source_outcome: null,
  suppressions: [],
  flags: [],
  failure: null,
};

test("a finished run is reopened from history, and nothing is run twice", async ({ page }) => {
  let runsStarted = 0;

  await page.route("**/api/research?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 1,
        limit: 20,
        offset: 0,
        runs: [
          {
            id: RESEARCH_ID,
            query: QUESTION,
            normalized_query: null,
            created_at: "2026-03-01T12:00:00Z",
            status: "completed",
            message: FINISHED,
            result_count: 1,
          },
        ],
      }),
    });
  });

  await page.route("**/api/research", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    runsStarted += 1;
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: RESEARCH_ID, status: "pending" }),
    });
  });

  await page.route(`**/api/research/${RESEARCH_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: RESEARCH_ID,
        status: "completed",
        message: FINISHED,
        query: QUESTION,
        normalized_query: null,
        created_at: "2026-03-01T12:00:00Z",
        statistics: { posts_analyzed: 38 },
        diagnostics: DIAGNOSTICS,
        clarification: null,
      }),
    });
  });

  await page.route(`**/api/research/${RESEARCH_ID}/results`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: RESEARCH_ID,
        status: "completed",
        message: FINISHED,
        percentages_suppressed: false,
        provisional: false,
        weak_results: [],
        minimum_independent_users: 5,
        results: [
          {
            entity_id: "state:alaska",
            entity_name: "Alaska",
            supporter_count: 47,
            share: 0.42,
            respondent_pool_size: 112,
            discussion_count: 38,
            weighted_score: 40.2,
            confidence: 0.9,
            explanation: "Frequently cited for untouched wilderness.",
            evidence_permalinks: [],
          },
        ],
      }),
    });
  });

  // Start a run. It gets its own URL, not a place in the page's memory.
  await page.goto("/");
  await page.getByLabel(/what are you trying to find/i).fill(QUESTION);
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page).toHaveURL(new RegExp(`/research/${RESEARCH_ID}$`));
  await expect(page.getByText("Alaska")).toBeVisible();
  await expect(page.getByText(/42% of people who answered mentioned this\./)).toBeVisible();

  // Navigate away — the run is over, and the tab moves on.
  await page.getByRole("link", { name: "History" }).click();
  await expect(page).toHaveURL(/\/history$/);
  await expect(page.getByText("Alaska")).toHaveCount(0);

  const row = page.getByRole("link", { name: new RegExp(QUESTION) });
  await expect(row).toBeVisible();
  await expect(row.getByText("Finished", { exact: true })).toBeVisible();

  // And back in, at the run's own URL, showing what it showed before.
  await row.click();
  await expect(page).toHaveURL(new RegExp(`/research/${RESEARCH_ID}$`));
  await expect(page.getByRole("heading", { name: QUESTION })).toBeVisible();
  await expect(page.getByText("Alaska")).toBeVisible();
  await expect(page.getByText(/42% of people who answered mentioned this\./)).toBeVisible();
  await expect(page.getByText("Frequently cited for untouched wilderness.")).toBeVisible();

  // One run was ever started, and reopening it started nothing.
  expect(runsStarted).toBe(1);
});

test("an empty history says so rather than looking broken", async ({ page }) => {
  await page.route("**/api/research?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ total: 0, limit: 20, offset: 0, runs: [] }),
    });
  });

  await page.goto("/history");

  await expect(page.getByText(/no research yet/i)).toBeVisible();
});
