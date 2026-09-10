import { test, expect } from "@playwright/test";

const RESEARCH_ID = "11111111-1111-1111-1111-111111111111";

const DIAGNOSTICS = {
  source_health: [],
  source_outcome: null,
  suppressions: [],
  flags: [],
  failure: null,
};

test("search a query and drill into evidence for the top result", async ({ page }) => {
  let statusCalls = 0;

  await page.route("**/api/research", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: RESEARCH_ID, status: "pending" }),
    });
  });

  await page.route(`**/api/research/${RESEARCH_ID}`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    statusCalls += 1;
    const status = statusCalls === 1 ? "pending" : "completed";
    const message =
      status === "pending"
        ? "Queued. This research has not started yet."
        : "Finished. Every discussion we set out to read was read, so these counts reflect what people actually said.";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: RESEARCH_ID,
        status,
        message,
        statistics: status === "pending" ? {} : { posts_analyzed: 38 },
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
        message: "Finished. Every discussion we set out to read was read, so these counts reflect what people actually said.",
        percentages_suppressed: false,
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
            evidence_permalinks: ["https://reddit.com/r/example/1"],
          },
        ],
      }),
    });
  });

  await page.route(`**/api/research/${RESEARCH_ID}/evidence**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        entity_id: "state:alaska",
        entity_name: "Alaska",
        total: 1,
        limit: 10,
        offset: 0,
        permalinks: ["https://reddit.com/r/example/1"],
      }),
    });
  });

  await page.goto("/");

  await page.getByLabel(/what are you trying to find/i).fill("most underrated US states for nature");
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page.getByText("Alaska")).toBeVisible();
  await expect(page.getByText(/42% of people who answered mentioned this\./)).toBeVisible();
  await expect(page.getByText(/Based on 112 people across 38 discussions\./)).toBeVisible();

  await page.getByRole("button", { name: "View evidence" }).click();
  await expect(page.getByRole("link", { name: "https://reddit.com/r/example/1" })).toBeVisible();
});
