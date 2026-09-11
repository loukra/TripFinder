import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProgressView } from "./ProgressView";

describe("ProgressView", () => {
  it("shows the status and message", () => {
    render(
      <ProgressView
        status="discovering"
        message="Searching for discussions that answer your question."
        statistics={{ posts_found: 12 }}
        onCancel={vi.fn()}
        cancelling={false}
      />
    );

    expect(screen.getByText("discovering")).toBeInTheDocument();
    expect(screen.getByText(/searching for discussions/i)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("cancels on click", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <ProgressView status="pending" message="Queued." statistics={{}} onCancel={onCancel} cancelling={false} />
    );

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalled();
  });

  it("disables the cancel button while cancelling", () => {
    render(
      <ProgressView status="pending" message="Queued." statistics={{}} onCancel={vi.fn()} cancelling={true} />
    );

    expect(screen.getByRole("button", { name: "Cancelling…" })).toBeDisabled();
  });

  it("marks stages done, active and waiting from the reported status", () => {
    render(
      <ProgressView
        status="retrieving"
        message="Pulling comment trees."
        statistics={{}}
        onCancel={vi.fn()}
        cancelling={false}
      />
    );

    const row = (label: string) => within(screen.getByText(label).closest("li")!);

    expect(row("Understanding the question").getByText("Done")).toBeInTheDocument();
    expect(row("Searching discussions").getByText("Done")).toBeInTheDocument();
    expect(row("Retrieving comments").getByText("In progress")).toBeInTheDocument();
    expect(row("Analysing opinions").getByText("Waiting")).toBeInTheDocument();
    expect(row("Counting independent people").getByText("Waiting")).toBeInTheDocument();
  });

  // The checklist must never imply work that has not happened: `pending` is a
  // running status that sits before the first pipeline stage.
  it("claims no stage progress while the run is still pending", () => {
    render(
      <ProgressView status="pending" message="Queued." statistics={{}} onCancel={vi.fn()} cancelling={false} />
    );

    expect(screen.getAllByText("Waiting")).toHaveLength(5);
    expect(screen.queryByText("Done")).not.toBeInTheDocument();
    expect(screen.queryByText("In progress")).not.toBeInTheDocument();
  });
});
