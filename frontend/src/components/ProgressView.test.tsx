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
        onCancel={vi.fn()}
        cancelling={false}
      />
    );

    expect(screen.getByText("Searching")).toBeInTheDocument();
    expect(screen.getByText(/searching for discussions/i)).toBeInTheDocument();
  });

  // The time limit binds by design, so a run that hit it is a result like
  // any other — with one short line saying not everything was read.
  it("calls a run stopped by its time limit complete, and says so under the stages", () => {
    render(<ProgressView status="completed_partial" message="Stopped at the time limit." />);

    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("Stopped at the time limit.")).toBeInTheDocument();
  });

  it("adds no note to a run that read everything", () => {
    render(<ProgressView status="completed" message="Finished." />);

    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.queryByText("Finished.")).not.toBeInTheDocument();
  });

  it("cancels on click", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <ProgressView status="pending" message="Queued." onCancel={onCancel} cancelling={false} />
    );

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalled();
  });

  it("disables the cancel button while cancelling", () => {
    render(
      <ProgressView status="pending" message="Queued." onCancel={vi.fn()} cancelling={true} />
    );

    expect(screen.getByRole("button", { name: "Cancelling…" })).toBeDisabled();
  });

  it("marks stages done, active and waiting from the reported status", () => {
    render(
      <ProgressView
        status="retrieving"
        message="Pulling comment trees."
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

  // The column stays beside the ranking after the run ends so the results do
  // not move on the page; a finished run has passed every stage, and there is
  // nothing left to cancel.
  it("marks every stage done for a finished run and offers no cancel", () => {
    render(<ProgressView status="completed" message="Counted 417 people." />);

    expect(screen.getAllByText("Done")).toHaveLength(5);
    expect(screen.queryByText("In progress")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
  });

  // The checklist must never imply work that has not happened: `pending` is a
  // running status that sits before the first pipeline stage.
  it("claims no stage progress while the run is still pending", () => {
    render(
      <ProgressView status="pending" message="Queued." onCancel={vi.fn()} cancelling={false} />
    );

    expect(screen.getAllByText("Waiting")).toHaveLength(5);
    expect(screen.queryByText("Done")).not.toBeInTheDocument();
    expect(screen.queryByText("In progress")).not.toBeInTheDocument();
  });
});
