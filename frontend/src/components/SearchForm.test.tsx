import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SearchForm } from "./SearchForm";

describe("SearchForm", () => {
  it("submits the typed query", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<SearchForm onSubmit={onSubmit} disabled={false} />);

    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(onSubmit).toHaveBeenCalledWith("underrated states");
  });

  it("does not submit a blank query", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<SearchForm onSubmit={onSubmit} disabled={false} />);

    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("fills the query from an example", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<SearchForm onSubmit={onSubmit} disabled={false} />);

    await user.click(screen.getByRole("button", { name: "most underrated US states for nature" }));

    expect(screen.getByLabelText(/what are you trying to find/i)).toHaveValue(
      "most underrated US states for nature"
    );
  });

  it("disables the input and button while disabled", () => {
    render(<SearchForm onSubmit={vi.fn()} disabled={true} />);

    expect(screen.getByLabelText(/what are you trying to find/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
  });
});
