import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClarificationView } from "./ClarificationView";
import type { ClarificationRequest } from "@/lib/types";

const clarification: ClarificationRequest = {
  question: "What kind of places are you looking for?",
  options: [
    { label: "States and regions", entity_granularity: "state" },
    { label: "National parks and natural areas", entity_granularity: "park" },
    { label: "Towns and small cities", entity_granularity: "town" },
  ],
  allow_grouped: true,
};

describe("ClarificationView", () => {
  it("renders the question and every option", () => {
    render(<ClarificationView clarification={clarification} onAnswer={vi.fn()} submitting={false} />);

    expect(screen.getByText(clarification.question)).toBeInTheDocument();
    for (const option of clarification.options) {
      expect(screen.getByText(option.label)).toBeInTheDocument();
    }
  });

  it("never offers a grouped option the backend cannot accept", () => {
    render(<ClarificationView clarification={clarification} onAnswer={vi.fn()} submitting={false} />);

    expect(screen.queryByText(/grouped/i)).not.toBeInTheDocument();
  });

  it("answers with the selected granularity", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn();
    render(<ClarificationView clarification={clarification} onAnswer={onAnswer} submitting={false} />);

    await user.click(screen.getByLabelText("Towns and small cities"));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(onAnswer).toHaveBeenCalledWith("town");
  });

  it("disables continue until an option is chosen", () => {
    render(<ClarificationView clarification={clarification} onAnswer={vi.fn()} submitting={false} />);

    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });
});
