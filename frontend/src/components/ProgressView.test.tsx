import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
});
