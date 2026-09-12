import { test, expect } from "@playwright/test";

// Phase 14.10 acceptance (plan §2.15): a question already answered is
// answered from the earlier run, that answer says when it was produced
// everywhere it is shown, and a fresh run is one click away and never
// consults the cache.

const ORIGINAL_ID = "11111111-1111-1111-1111-111111111111";
const REUSING_ID = "22222222-2222-2222-2222-222222222222";
const FRESH_ID = "33333333-3333-3333-3333-333333333333";

const QUESTION = "which US states are most underrated for nature";
const FINISHED =
  "Finished. Every discussion we set out to read was read, so these counts reflect what people actually said.";
const REUSED = { research_id: ORIGINAL_ID, answered_at: "2026-03-04T09:30:00Z" };

const DIAGNOSTICS = {
  source_health: [],
  source_outcome: null,
  suppressions: [],
  flags: [],
  failure: null,
};

const RANKING = [
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
];

function status(id: string, reused: typeof REUSED | null) {
  return {
    id,
    status: "completed",
    message: FINISHED,
    query: QUESTION,
    normalized_query: null,
    created_at: "2026-09-12T08:00:00Z",
    reused,
    statistics: { posts_analyzed: 38, llm_calls: reused ? 1 : 131 },
    diagnostics: DIAGNOSTICS,
    clarification: null,
  };
}

function results(id: string, reused: typeof REUSED | null) {
  return {
    id,
    status: "completed",
    message: FINISHED,
    percentages_suppressed: false,
    provisional: false,
    weak_results: [],
    minimum_independent_users: 5,
    reused,
    results: RANKING,
  };
}

test("a reused answer is dated wherever it is shown, and a fresh run is one click away", async ({
  page,
}) => {
  const created: { query: string; fresh: boolean }[] = [];

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
            id: REUSING_ID,
            query: QUESTION,
            normalized_query: null,
            created_at: "2026-09-12T08:00:00Z",
            status: "completed",
            message: FINISHED,
            result_count: 1,
            reused: REUSED,
          },
        ],
      }),
    });
  });

  await page.route("**/api/research", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = route.request().postDataJSON() as { query: string; fresh: boolean };
    created.push(body);
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: body.fresh ? FRESH_ID : REUSING_ID, status: "pending" }),
    });
  });

  for (const [id, reused] of [
    [REUSING_ID, REUSED],
    [FRESH_ID, null],
    [ORIGINAL_ID, null],
  ] as const) {
    await page.route(`**/api/research/${id}`, async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(status(id, reused)),
      });
    });
    await page.route(`**/api/research/${id}/results`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(results(id, reused)),
      });
    });
  }

  // Ask a question that has been answered before.
  await page.goto("/");
  await page.getByLabel(/what are you trying to find/i).fill(QUESTION);
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page).toHaveURL(new RegExp(`/research/${REUSING_ID}$`));
  await expect(page.getByText("Alaska")).toBeVisible();

  // The answer is dated on the page it is read on.
  const note = page.getByRole("note");
  await expect(note).toContainText("Answered on 4 March 2026");
  // And it is not described as unfinished — a different thing entirely.
  await expect(page.getByText(/still counting/i)).toHaveCount(0);

  // The same answer, listed in history, carries the same date.
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByText(/Answered on 4 March 2026/)).toBeVisible();

  // Back to the run, and take the offer of a fresh one.
  await page.getByRole("link", { name: new RegExp(QUESTION) }).click();
  await expect(page).toHaveURL(new RegExp(`/research/${REUSING_ID}$`));
  await page.getByRole("button", { name: "Research it again" }).click();

  // A new run, at its own URL, and this one is nobody's copy.
  await expect(page).toHaveURL(new RegExp(`/research/${FRESH_ID}$`));
  await expect(page.getByRole("note")).toHaveCount(0);
  await expect(page.getByText("Alaska")).toBeVisible();

  expect(created).toEqual([
    { query: QUESTION, fresh: false },
    { query: QUESTION, fresh: true },
  ]);
});

test("the original run is reachable from the answer that reused it", async ({ page }) => {
  await page.route(`**/api/research/${REUSING_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(status(REUSING_ID, REUSED)),
    });
  });
  await page.route(`**/api/research/${REUSING_ID}/results`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(results(REUSING_ID, REUSED)),
    });
  });
  await page.route(`**/api/research/${ORIGINAL_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(status(ORIGINAL_ID, null)),
    });
  });
  await page.route(`**/api/research/${ORIGINAL_ID}/results`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(results(ORIGINAL_ID, null)),
    });
  });

  await page.goto(`/research/${REUSING_ID}`);

  await page.getByRole("link", { name: "See the original run" }).click();

  await expect(page).toHaveURL(new RegExp(`/research/${ORIGINAL_ID}$`));
  await expect(page.getByRole("note")).toHaveCount(0);
});
