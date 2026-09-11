import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResultsView } from "./ResultsView";
import * as api from "@/lib/api";
import type { ResearchResultsResponse } from "@/lib/types";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof api>("@/lib/api");
  return { ...actual, getEvidence: vi.fn() };
});

function makeData(overrides: Partial<ResearchResultsResponse> = {}): ResearchResultsResponse {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    status: "completed",
    message: "Finished.",
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
      {
        entity_id: "state:oregon",
        entity_name: "Oregon",
        supporter_count: 24,
        share: 0.21,
        respondent_pool_size: 112,
        discussion_count: 20,
        weighted_score: 21.1,
        confidence: 0.85,
        explanation: null,
        evidence_permalinks: [],
      },
    ],
    ...overrides,
  };
}

describe("ResultsView", () => {
  it("shows the exact percentage label and denominator wording", () => {
    render(<ResultsView researchId="r1" data={makeData()} />);

    expect(screen.getByText(/42% of people who answered mentioned this\./)).toBeInTheDocument();
    expect(screen.getByText(/Based on 112 people across 38 discussions\./)).toBeInTheDocument();
    expect(screen.getByText("47", { exact: false })).toBeInTheDocument();
  });

  it("withholds the percentage when share is null", () => {
    const data = makeData({
      percentages_suppressed: true,
      results: [
        {
          entity_id: "state:alaska",
          entity_name: "Alaska",
          supporter_count: 47,
          share: null,
          respondent_pool_size: 112,
          discussion_count: 38,
          weighted_score: 40.2,
          confidence: 0.9,
          explanation: null,
          evidence_permalinks: [],
        },
      ],
    });

    render(<ResultsView researchId="r1" data={data} />);

    expect(screen.getByText(/Percentage withheld\./)).toBeInTheDocument();
    expect(screen.queryByText(/% of people who answered/)).not.toBeInTheDocument();
    expect(screen.getByText(/Percentages are withheld for this run/)).toBeInTheDocument();
  });

  it("shows an empty state when there are no results", () => {
    render(<ResultsView researchId="r1" data={makeData({ results: [] })} />);

    expect(screen.getByText(/no entities gathered enough independent supporters/i)).toBeInTheDocument();
  });

  it("loads evidence on demand for a result", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getEvidence).mockResolvedValue({
      entity_id: "state:alaska",
      entity_name: "Alaska",
      total: 1,
      limit: 10,
      offset: 0,
      permalinks: ["https://reddit.com/r/example/1"],
    });

    render(<ResultsView researchId="r1" data={makeData()} />);

    await user.click(screen.getAllByRole("button", { name: "View evidence" })[0]);

    expect(await screen.findByText("https://reddit.com/r/example/1")).toBeInTheDocument();
    expect(api.getEvidence).toHaveBeenCalledWith("r1", "state:alaska", 10, 0);
  });

  it("bands the numeric confidence into a readable badge", () => {
    const base = makeData().results[0];
    const data = makeData({
      results: [
        { ...base, entity_id: "a", entity_name: "Alaska", confidence: 0.9 },
        { ...base, entity_id: "b", entity_name: "Oregon", confidence: 0.5 },
        { ...base, entity_id: "c", entity_name: "Maine", confidence: 0.1 },
      ],
    });

    render(<ResultsView researchId="r1" data={data} />);

    expect(screen.getByText("high confidence")).toBeInTheDocument();
    expect(screen.getByText("medium confidence")).toBeInTheDocument();
    expect(screen.getByText("low confidence")).toBeInTheDocument();
  });
});
