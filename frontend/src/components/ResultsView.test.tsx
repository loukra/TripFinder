import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResultsView } from "./ResultsView";
import * as api from "@/lib/api";
import type { ResearchResultsResponse, ResultItem } from "@/lib/types";

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
    provisional: false,
    weak_results: [],
    minimum_independent_users: 5,
    reused: null,
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
  // The written reason a place is in the top five. It comes from
  // Summarization (plan §4.6 step 13) and is the only prose on the page that
  // says *why* — and it is null far more often than it should be, because
  // the grounding check has twice rejected the model's own citations over
  // formatting. Nothing asserted it reached the screen until now.
  it("prints the explanation under the result it belongs to", () => {
    render(<ResultsView researchId="r1" data={makeData()} />);

    const alaska = screen.getByText("Alaska").closest("li")!;
    expect(
      within(alaska).getByText("Frequently cited for untouched wilderness.")
    ).toBeInTheDocument();
  });

  it("leaves no empty paragraph for a result that has no explanation", () => {
    const { container } = render(<ResultsView researchId="r1" data={makeData()} />);

    // Two results, one of them with `explanation: null`.
    expect(container.querySelectorAll(".result-explanation")).toHaveLength(1);
  });

  // A finished row with no summary had one withheld, usually by the quote
  // check. A blank there reads as a bug; the row says what happened instead.
  it("says why a finished result has no summary", () => {
    render(<ResultsView researchId="r1" data={makeData()} />);

    const oregon = screen.getByText("Oregon").closest("li")!;
    expect(within(oregon).getByText(/No summary available/)).toBeInTheDocument();
    const alaska = screen.getByText("Alaska").closest("li")!;
    expect(within(alaska).queryByText(/No summary available/)).not.toBeInTheDocument();
  });

  it("shows the explanation on a provisional ranking too", () => {
    render(<ResultsView researchId="r1" data={makeData({ provisional: true })} />);

    expect(
      screen.getByText("Frequently cited for untouched wilderness.")
    ).toBeInTheDocument();
  });

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

function makeResult(overrides: Partial<ResultItem> = {}): ResultItem {
  return {
    entity_id: "state:vermont",
    entity_name: "Vermont",
    supporter_count: 2,
    share: null,
    respondent_pool_size: 9,
    discussion_count: 3,
    weighted_score: 1.8,
    confidence: 0.7,
    explanation: null,
    evidence_permalinks: [],
    ...overrides,
  };
}

function makeProvisional(
  overrides: Partial<ResearchResultsResponse> = {}
): ResearchResultsResponse {
  return makeData({
    status: "analyzing",
    message: "Still reading.",
    percentages_suppressed: true,
    provisional: true,
    results: [],
    weak_results: [
      makeResult(),
      makeResult({ entity_id: "state:maine", entity_name: "Maine", supporter_count: 1 }),
    ],
    ...overrides,
  });
}

// Plan §2.13: an unfinished ranking, shown honestly.
describe("ResultsView, while a run is still counting", () => {
  it("says the numbers are still growing", () => {
    render(<ResultsView researchId="r1" data={makeProvisional()} />);

    expect(screen.getByText(/still counting/i)).toBeInTheDocument();
  });

  it("shows the weak list as candidates rather than an empty ranking", () => {
    render(<ResultsView researchId="r1" data={makeProvisional()} />);

    expect(screen.getByRole("heading", { name: /not enough people yet/i })).toBeInTheDocument();
    expect(screen.getByText("Vermont")).toBeInTheDocument();
    expect(screen.getByText("Maine")).toBeInTheDocument();
    expect(
      screen.queryByText(/no entities gathered enough independent supporters/i)
    ).not.toBeInTheDocument();
  });

  it("never pads the strong list to reach five", () => {
    render(<ResultsView researchId="r1" data={makeProvisional()} />);

    // Everything on the page is under the threshold, and the page says so
    // instead of promoting anything into the headline list.
    expect(screen.queryByRole("heading", { name: /ahead so far/i })).not.toBeInTheDocument();
    expect(screen.getByText(/fewer than 5 different people/i)).toBeInTheDocument();
  });

  it("does not claim too few supporters for an entity that merely missed the cap", () => {
    // §4.4 caps the headline list at five, so an entity with 28 supporters
    // can sit in weak_results with plenty of people behind it. Describing
    // that as "fewer than five people" states something false about a real
    // count.
    const data = makeProvisional({
      weak_results: [
        makeResult({ entity_id: "state:arkansas", entity_name: "Arkansas", supporter_count: 28 }),
        makeResult({ entity_id: "state:maine", entity_name: "Maine", supporter_count: 1 }),
      ],
    });

    render(<ResultsView researchId="r1" data={data} />);

    expect(screen.getByRole("heading", { name: /also ranked/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /not enough people yet/i })).toBeInTheDocument();
    expect(screen.getByText(/the list above shows at most five/i)).toBeInTheDocument();
    expect(screen.getByText(/fewer than 5 different people/i)).toBeInTheDocument();
  });

  it("states the respondent pool once, not beside every count", () => {
    // "Based on 417 people" repeated under a row whose own count is 28 is
    // two different scopes in one sentence, and reads as one number.
    const data = makeProvisional({
      weak_results: [makeResult({ supporter_count: 3, respondent_pool_size: 417 })],
    });

    render(<ResultsView researchId="r1" data={data} />);

    expect(screen.getByText(/417 people have given an opinion we can count so far/i)).toBeInTheDocument();
    expect(screen.queryByText(/Based on 417 people/)).not.toBeInTheDocument();
    expect(screen.getByText(/Recommended in 3 discussions so far\./)).toBeInTheDocument();
  });

  it("reads as not-yet-computable rather than as a defect", () => {
    render(<ResultsView researchId="r1" data={makeProvisional()} />);

    expect(screen.getAllByText(/no percentage yet/i).length).toBe(2);
    expect(screen.queryByText(/Percentage withheld\./)).not.toBeInTheDocument();
    expect(screen.queryByText(/Percentages are withheld for this run/)).not.toBeInTheDocument();
  });

  // The provisional ranking is drawn as the finished one: same rows, same
  // ranks, same position on the page, with the banner — not a different
  // layout — carrying the claim that it is still moving (plan §2.13.1: an
  // order that may still change is honest under an explicit label).
  it("ranks the list as the finished view does, under a provisional label", () => {
    const data = makeProvisional({
      results: [makeResult({ entity_id: "state:alaska", entity_name: "Alaska", supporter_count: 6 })],
    });

    render(<ResultsView researchId="r1" data={data} />);

    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText(/provisional result/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /ahead so far/i })).not.toBeInTheDocument();
  });

  it("says nothing has been counted yet when nothing has", () => {
    const data = makeProvisional({ results: [], weak_results: [] });

    render(<ResultsView researchId="r1" data={data} />);

    expect(screen.getByText(/nothing counted yet/i)).toBeInTheDocument();
  });

  it("keeps updating while the pointer rests on the list", async () => {
    // The first version of the hold froze on hover, so a pointer left
    // anywhere on the list stopped the page — under a banner still
    // promising the numbers were growing.
    const user = userEvent.setup();
    const vermont = makeResult({ supporter_count: 2 });
    const maine = makeResult({
      entity_id: "state:maine",
      entity_name: "Maine",
      supporter_count: 1,
    });
    const { rerender } = render(
      <ResultsView researchId="r1" data={makeProvisional({ weak_results: [vermont, maine] })} />
    );

    await user.hover(screen.getByText("Vermont").closest("li")!);
    rerender(
      <ResultsView
        researchId="r1"
        data={makeProvisional({ weak_results: [{ ...maine, supporter_count: 9 }, vermont] })}
      />
    );

    expect(namesInOrder()).toEqual(["Maine", "Vermont"]);
  });

  it("shows the finished answer even while evidence is open", async () => {
    // The defect this exists to prevent: a run finished at 66 supporters
    // while the page went on showing a provisional 32 and "still counting",
    // because an open panel held the view past the end of the run. A view
    // that withholds the finished result is worse than one that reorders.
    const user = userEvent.setup();
    vi.mocked(api.getEvidence).mockResolvedValue({
      entity_id: "state:vermont",
      entity_name: "Vermont",
      total: 0,
      limit: 10,
      offset: 0,
      permalinks: [],
    });
    const { rerender } = render(
      <ResultsView
        researchId="r1"
        data={makeProvisional({ weak_results: [makeResult({ supporter_count: 32 })] })}
      />
    );

    await user.click(screen.getAllByRole("button", { name: "View evidence" })[0]);
    expect(screen.getByText(/still counting/i)).toBeInTheDocument();

    rerender(
      <ResultsView
        researchId="r1"
        data={{
          ...makeProvisional(),
          status: "completed_partial",
          provisional: false,
          percentages_suppressed: false,
          results: [makeResult({ supporter_count: 66, share: 0.103 })],
          weak_results: [],
        }}
      />
    );

    expect(screen.getByText("66")).toBeInTheDocument();
    expect(screen.queryByText("32")).not.toBeInTheDocument();
    expect(screen.queryByText(/still counting/i)).not.toBeInTheDocument();
  });

  it("holds a reorder while an evidence panel is open, even after the mouse leaves", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getEvidence).mockResolvedValue({
      entity_id: "state:vermont",
      entity_name: "Vermont",
      total: 0,
      limit: 10,
      offset: 0,
      permalinks: [],
    });
    const vermont = makeResult({ supporter_count: 2 });
    const maine = makeResult({
      entity_id: "state:maine",
      entity_name: "Maine",
      supporter_count: 1,
    });
    const { rerender } = render(
      <ResultsView researchId="r1" data={makeProvisional({ weak_results: [vermont, maine] })} />
    );

    await user.click(screen.getAllByRole("button", { name: "View evidence" })[0]);
    await user.unhover(screen.getByText("Vermont").closest("li")!);
    rerender(
      <ResultsView
        researchId="r1"
        data={makeProvisional({ weak_results: [{ ...maine, supporter_count: 9 }, vermont] })}
      />
    );

    expect(namesInOrder()).toEqual(["Vermont", "Maine"]);
  });
});

describe("a reused answer (plan §2.15)", () => {
  const REUSED = { research_id: "r0", answered_at: "2026-03-04T09:30:00Z" };

  it("says the date the answer was produced", () => {
    render(<ResultsView researchId="r1" data={makeData({ reused: REUSED })} />);

    expect(screen.getByRole("note")).toHaveTextContent("Answered on 4 March 2026");
  });

  it("says it even when the ranking came out empty", () => {
    // The empty state is the easiest place for a label to be forgotten, and
    // the worst place to forget it: "nothing found" from six months ago is
    // a claim about today unless it is dated.
    render(
      <ResultsView
        researchId="r1"
        data={makeData({ results: [], weak_results: [], reused: REUSED })}
      />
    );

    expect(screen.getByRole("note")).toHaveTextContent("Answered on 4 March 2026");
  });

  it("links to the run the answer came from", () => {
    render(<ResultsView researchId="r1" data={makeData({ reused: REUSED })} />);

    expect(screen.getByRole("link", { name: "See the original run" })).toHaveAttribute(
      "href",
      "/research/r0"
    );
  });

  it("offers a fresh run, and asks for one when clicked", async () => {
    const user = userEvent.setup();
    const onRunAgain = vi.fn();
    render(
      <ResultsView researchId="r1" data={makeData({ reused: REUSED })} onRunAgain={onRunAgain} />
    );

    await user.click(screen.getByRole("button", { name: "Research it again" }));

    expect(onRunAgain).toHaveBeenCalledOnce();
  });

  it("still says the date when nothing can be done about it", () => {
    // The label is not conditional on the page being able to offer a rerun.
    render(<ResultsView researchId="r1" data={makeData({ reused: REUSED })} />);

    expect(screen.queryByRole("button", { name: "Research it again" })).toBeNull();
    expect(screen.getByRole("note")).toHaveTextContent("Answered on 4 March 2026");
  });

  it("says nothing at all when the run did its own work", () => {
    render(<ResultsView researchId="r1" data={makeData()} />);

    expect(screen.queryByRole("note")).toBeNull();
  });

  it("does not describe a reused answer as provisional", () => {
    // Two different things a ranking can fail to be, and §0.1 rule 4 says
    // they may not share wording: one is unfinished, the other is finished
    // and old.
    render(<ResultsView researchId="r1" data={makeData({ reused: REUSED })} />);

    expect(screen.queryByText(/still counting/i)).toBeNull();
    expect(screen.getByText(/42% of people who answered/)).toBeInTheDocument();
  });
});

function namesInOrder(): string[] {
  return screen
    .getAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent ?? "");
}
