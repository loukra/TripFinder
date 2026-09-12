import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RunStats } from "./RunStats";

describe("RunStats", () => {
  it("shows each counter with a readable label", () => {
    render(<RunStats statistics={{ comments_analyzed: 1500, posts_found: 12 }} />);

    expect(screen.getByText("1,500")).toBeInTheDocument();
    expect(screen.getByText("comments analyzed")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  // An empty grid beside the ranking would read as "nothing was read",
  // which is a claim about the run rather than about the payload.
  it("renders nothing when the run has reported no counters yet", () => {
    const { container } = render(<RunStats statistics={{}} />);

    expect(container).toBeEmptyDOMElement();
  });
});
