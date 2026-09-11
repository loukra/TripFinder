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

// Plan §2.13: the run reports while it is still reading, and the page has to
// say what those numbers are worth.
test("shows a provisional ranking while counting, then the finished one", async ({ page }) => {
  let statusCalls = 0;
  const analysing = () => statusCalls <= 2;

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
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: RESEARCH_ID,
        status: analysing() ? "analyzing" : "completed",
        message: analysing()
          ? "Working out what each comment recommends."
          : "Finished. Every discussion we set out to read was read, so these counts reflect what people actually said.",
        statistics: { comments_with_analysis: analysing() ? 160 : 840 },
        diagnostics: DIAGNOSTICS,
        clarification: null,
      }),
    });
  });

  await page.route(`**/api/research/${RESEARCH_ID}/results`, async (route) => {
    const provisional = analysing();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: RESEARCH_ID,
        status: provisional ? "analyzing" : "completed",
        message: provisional
          ? "Still reading. Every count below comes from a comment we have already analysed."
          : "Finished. Every discussion we set out to read was read, so these counts reflect what people actually said.",
        percentages_suppressed: provisional,
        provisional,
        minimum_independent_users: 5,
        results: provisional
          ? []
          : [
              {
                entity_id: "state:alaska",
                entity_name: "Alaska",
                supporter_count: 47,
                share: 0.42,
                respondent_pool_size: 112,
                discussion_count: 38,
                weighted_score: 40.2,
                confidence: 0.9,
                explanation: null,
                evidence_permalinks: [],
              },
            ],
        weak_results: provisional
          ? [
              {
                entity_id: "state:alaska",
                entity_name: "Alaska",
                supporter_count: 3,
                share: null,
                respondent_pool_size: 12,
                discussion_count: 2,
                weighted_score: 2.6,
                confidence: 0.8,
                explanation: null,
                evidence_permalinks: [],
              },
            ]
          : [],
      }),
    });
  });

  await page.goto("/");
  await page.getByLabel(/what are you trying to find/i).fill("most underrated US states for nature");
  await page.getByRole("button", { name: "Search" }).click();

  // Mid-run: counts, no percentage, and the list labelled for what it is.
  await expect(page.getByText(/still counting/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: /not enough people yet/i })).toBeVisible();
  await expect(page.getByText(/no percentage yet/i)).toBeVisible();
  await expect(page.getByText(/% of people who answered/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();

  // The corpus closes, and the percentage appears — the switch is itself
  // information: the denominator is now fixed.
  await expect(page.getByText(/42% of people who answered mentioned this\./)).toBeVisible();
  await expect(page.getByText(/still counting/i)).toHaveCount(0);
});
