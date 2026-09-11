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
