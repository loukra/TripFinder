import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "./page";
import * as api from "@/lib/api";
import type { ResearchResultsResponse, ResearchStatusResponse } from "@/lib/types";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof api>("@/lib/api");
  return {
    ...actual,
    createResearch: vi.fn(),
    getResearch: vi.fn(),
    getResults: vi.fn(),
    clarifyResearch: vi.fn(),
    cancelResearch: vi.fn(),
  };
});

function statusResponse(overrides: Partial<ResearchStatusResponse> = {}): ResearchStatusResponse {
  return {
    id: "r1",
    status: "pending",
    message: "Queued. This research has not started yet.",
    statistics: {},
    diagnostics: {
      source_health: [],
      source_outcome: null,
      suppressions: [],
      flags: [],
      failure: null,
    },
    clarification: null,
    ...overrides,
  };
}

const resultsResponse: ResearchResultsResponse = {
  id: "r1",
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
      explanation: null,
      evidence_permalinks: [],
    },
  ],
};

// A real, very short interval — not a fake one — so the interval-driven
// re-poll actually fires during the test without waiting out the production
// 2s default or fighting fake-timer/async-query interactions.
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_POLL_INTERVAL_MS", "10");
});

describe("Home page", () => {
  it("runs a search through to a completed results page", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });
    vi.mocked(api.getResearch)
      .mockResolvedValueOnce(statusResponse({ status: "pending" }))
      .mockResolvedValueOnce(statusResponse({ status: "discovering", message: "Searching." }))
      .mockResolvedValue(statusResponse({ status: "completed", message: resultsResponse.message }));
    vi.mocked(api.getResults).mockResolvedValue(resultsResponse);

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("pending")).toBeInTheDocument();
    expect(await screen.findByText("discovering")).toBeInTheDocument();

    expect(await screen.findByText("Alaska")).toBeInTheDocument();
    expect(screen.getByText(/42% of people who answered mentioned this\./)).toBeInTheDocument();
    expect(api.getResults).toHaveBeenCalledWith("r1");
  });

  it("walks the clarification loop before resuming", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });
    vi.mocked(api.getResearch)
      .mockResolvedValueOnce(
        statusResponse({
          status: "needs_clarification",
          message: "One question before we start searching.",
          clarification: {
            question: "What kind of places are you looking for?",
            options: [{ label: "States and regions", entity_granularity: "state" }],
            allow_grouped: true,
          },
        })
      )
      .mockResolvedValue(statusResponse({ status: "discovering", message: "Searching." }));
    vi.mocked(api.clarifyResearch).mockResolvedValue({ id: "r1", status: "discovering" });

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated destinations");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("What kind of places are you looking for?")).toBeInTheDocument();

    await user.click(screen.getByLabelText("States and regions"));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(api.clarifyResearch).toHaveBeenCalledWith("r1", "state");
    expect(await screen.findByText("discovering")).toBeInTheDocument();
  });

  it("shows a plain terminal message for a rejected research, with no results call", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });
    vi.mocked(api.getResearch).mockResolvedValue(
      statusResponse({
        status: "rejected",
        message: "This is not a travel recommendation question, so nothing was run.",
      })
    );

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "what's the capital of France");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(
      await screen.findByText("This is not a travel recommendation question, so nothing was run.")
    ).toBeInTheDocument();
    await waitFor(() => expect(api.getResults).not.toHaveBeenCalled());
  });

  it("cancels a running research", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });
    // Polling keeps reporting "discovering" on its own — only the explicit
    // cancel call should ever produce the "cancelled" status.
    vi.mocked(api.getResearch).mockResolvedValue(statusResponse({ status: "discovering", message: "Searching." }));
    vi.mocked(api.cancelResearch).mockResolvedValue(
      statusResponse({ status: "cancelled", message: "You cancelled this research before it finished." })
    );
    // Cancelled during discovery, so there is no snapshot to show and the
    // API says so with a 409 (plan §2.13.3). The page must not treat that as
    // an error — it is the ordinary shape of an early cancellation.
    vi.mocked(api.getResults).mockRejectedValue(
      new api.ApiError(409, { status: "cancelled", message: "no results" })
    );

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    const cancelButton = await screen.findByRole("button", { name: "Cancel" });
    await user.click(cancelButton);

    expect(api.cancelResearch).toHaveBeenCalledWith("r1");
    expect(await screen.findByText("You cancelled this research before it finished.")).toBeInTheDocument();
  });

  it("titles the run with the submitted query and can start a fresh one", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });
    vi.mocked(api.getResearch).mockResolvedValue(
      statusResponse({ status: "completed", message: resultsResponse.message })
    );
    vi.mocked(api.getResults).mockResolvedValue(resultsResponse);

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("heading", { name: "underrated states" })).toBeInTheDocument();
    expect(await screen.findByText("Alaska")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New research" }));

    expect(screen.getByLabelText(/what are you trying to find/i)).toBeInTheDocument();
    expect(screen.queryByText("Alaska")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "underrated states" })).not.toBeInTheDocument();
  });
});

// Plan §2.13: the page stops waiting five minutes for its first number.
describe("Home page, while a run is still counting", () => {
  it("shows a provisional ranking mid-run and keeps polling", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });
    vi.mocked(api.getResearch).mockResolvedValue(
      statusResponse({ status: "analyzing", message: "Working out what each comment recommends." })
    );
    vi.mocked(api.getResults).mockResolvedValue({
      ...resultsResponse,
      status: "analyzing",
      message: "Still reading.",
      percentages_suppressed: true,
      provisional: true,
      results: [{ ...resultsResponse.results[0], share: null, supporter_count: 6 }],
    });

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/still counting/i)).toBeInTheDocument();
    expect(screen.getByText("Alaska")).toBeInTheDocument();
    expect(screen.queryByText(/% of people who answered/)).not.toBeInTheDocument();
    // The progress view stays: the run is still working, and the ranking
    // below it is not a finished answer.
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("drops the provisional ranking if the run then fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });
    vi.mocked(api.getResearch)
      .mockResolvedValueOnce(statusResponse({ status: "analyzing", message: "Analysing." }))
      .mockResolvedValue(
        statusResponse({
          status: "failed",
          message: "Something went wrong inside this research. Nothing was produced.",
        })
      );
    vi.mocked(api.getResults).mockResolvedValue({
      ...resultsResponse,
      status: "analyzing",
      message: "Still reading.",
      percentages_suppressed: true,
      provisional: true,
      results: [{ ...resultsResponse.results[0], share: null }],
    });

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/still counting/i)).toBeInTheDocument();
    // A failed run has no results object at all (§8.1 rule 1, §0.1 rule 3):
    // leaving the last snapshot on screen would let it keep displaying a
    // ranking as though it had finished one.
    expect(
      await screen.findByText("Something went wrong inside this research. Nothing was produced.")
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Alaska")).not.toBeInTheDocument());
  });
});
