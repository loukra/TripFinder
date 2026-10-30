import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { RunStats } from "./RunStats";

describe("RunStats", () => {
  it("shows each counter with a readable label", () => {
    render(<RunStats statistics={{ comments_analyzed: 1500, posts_found: 12 }} />);

    expect(screen.getByText("1,500")).toBeInTheDocument();
    expect(screen.getByText("comments analysed")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("posts found")).toBeInTheDocument();
  });

  // The headline counters stay in view; the diagnostic rest is folded away
  // but never dropped.
  it("folds everything but the headline counters into a disclosure", () => {
    const { container } = render(
      <RunStats statistics={{ respondent_pool_size: 524, strands_failed: 0 }} />
    );

    expect(screen.getByText("people who answered")).toBeInTheDocument();
    const more = container.querySelector("details")!;
    expect(more).not.toHaveAttribute("open");
    expect(within(more).getByText("strands failed")).toBeInTheDocument();
    expect(within(more).getByText("All counters (1)")).toBeInTheDocument();
  });

  // An empty grid beside the ranking would read as "nothing was read",
  // which is a claim about the run rather than about the payload.
  it("renders nothing when the run has reported no counters yet", () => {
    const { container } = render(<RunStats statistics={{}} />);

    expect(container).toBeEmptyDOMElement();
  });
});
