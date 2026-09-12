import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "./page";
import * as api from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof api>("@/lib/api");
  return { ...actual, createResearch: vi.fn() };
});

beforeEach(() => {
  push.mockClear();
});

describe("The landing page", () => {
  // Plan §2.15: a run has its own URL, and starting one goes there. A run
  // that lives only in this page's state dies with the tab, which is the
  // thing Phase 14.9 exists to stop.
  it("sends a new research to its own URL", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockResolvedValue({ id: "r1", status: "pending" });

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(api.createResearch).toHaveBeenCalledWith("underrated states");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/research/r1"));
  });

  it("stays put and says why when the research cannot be started", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createResearch).mockRejectedValue(
      new api.ApiError(503, { message: "the database is unreachable" })
    );

    render(<Home />);
    await user.type(screen.getByLabelText(/what are you trying to find/i), "underrated states");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("the database is unreachable")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    // Still usable: the failure must not leave the form disabled for ever.
    expect(screen.getByRole("button", { name: "Search" })).toBeEnabled();
  });
});
