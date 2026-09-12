import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HistoryPage from "./page";
import * as api from "@/lib/api";
import type { ResearchListItem, ResearchListResponse } from "@/lib/types";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof api>("@/lib/api");
  return { ...actual, listResearch: vi.fn() };
});

function listItem(overrides: Partial<ResearchListItem> = {}): ResearchListItem {
  return {
    id: "r1",
    query: "underrated states for nature",
    normalized_query: null,
    created_at: "2026-03-01T12:00:00Z",
    status: "completed",
    message: "Finished. Every discussion we set out to read was read.",
    result_count: 5,
    ...overrides,
  };
}

function page(runs: ResearchListItem[], total = runs.length): ResearchListResponse {
  return { total, limit: 20, offset: 0, runs };
}

describe("The history page", () => {
  it("lists past runs newest first, each linking to its own run", async () => {
    vi.mocked(api.listResearch).mockResolvedValue(
      page([
        listItem({ id: "r2", query: "underrated countries", created_at: "2026-03-02T09:00:00Z" }),
        listItem({ id: "r1", query: "underrated states", created_at: "2026-03-01T12:00:00Z" }),
      ])
    );

    render(<HistoryPage />);

    const rows = await screen.findAllByRole("link", { name: /underrated/ });
    expect(rows.map((row) => row.getAttribute("href"))).toEqual([
      "/research/r2",
      "/research/r1",
    ]);
    expect(within(rows[0]).getByText("underrated countries")).toBeInTheDocument();
    // The date is machine-readable, whatever the reader's locale renders.
    expect(rows[0].querySelector("time")).toHaveAttribute("datetime", "2026-03-02T09:00:00Z");
  });

  // Plan §0.1 rule 4, one status ahead of the click: the list has to
  // separate a run that finished from one that was cut short, broke, or was
  // stopped — not colour them all "done".
  it("tells the outcomes apart at a glance", async () => {
    vi.mocked(api.listResearch).mockResolvedValue(
      page([
        listItem({ id: "r1", query: "finished one", status: "completed" }),
        listItem({ id: "r2", query: "cut short", status: "completed_partial" }),
        listItem({ id: "r3", query: "broken one", status: "failed", result_count: null }),
        listItem({ id: "r4", query: "stopped one", status: "cancelled", result_count: null }),
      ])
    );

    render(<HistoryPage />);

    const row = async (name: string) => await screen.findByRole("link", { name: new RegExp(name) });
    expect(within(await row("finished one")).getByText("Finished")).toBeInTheDocument();
    expect(within(await row("cut short")).getByText("Stopped early")).toBeInTheDocument();
    expect(within(await row("broken one")).getByText("Failed")).toBeInTheDocument();
    expect(within(await row("stopped one")).getByText("Cancelled")).toBeInTheDocument();
  });

  // A run with no results page has no count — not a count of zero, which
  // would say it looked and found nothing (plan §0.1).
  it("counts the ranked places only for runs that have a results page", async () => {
    vi.mocked(api.listResearch).mockResolvedValue(
      page([
        listItem({ id: "r1", query: "finished one", result_count: 5 }),
        listItem({ id: "r2", query: "broken one", status: "failed", result_count: null }),
      ])
    );

    render(<HistoryPage />);

    const finished = await screen.findByRole("link", { name: /finished one/ });
    expect(within(finished).getByText("5 ranked places")).toBeInTheDocument();
    const broken = await screen.findByRole("link", { name: /broken one/ });
    expect(within(broken).queryByText(/ranked/)).not.toBeInTheDocument();
  });

  it("says plainly that there is nothing here yet", async () => {
    vi.mocked(api.listResearch).mockResolvedValue(page([], 0));

    render(<HistoryPage />);

    expect(await screen.findByText(/no research yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not load/i)).not.toBeInTheDocument();
  });

  // An empty history and a history that could not be read are different
  // things, and the page must never show the first when it means the second.
  it("does not pass a failed load off as an empty history", async () => {
    vi.mocked(api.listResearch).mockRejectedValue(
      new api.ApiError(503, { message: "the database is unreachable" })
    );

    render(<HistoryPage />);

    expect(await screen.findByText("the database is unreachable")).toBeInTheDocument();
    expect(screen.queryByText(/no research yet/i)).not.toBeInTheDocument();
  });

  it("fetches the next page only when asked for it", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listResearch)
      .mockResolvedValueOnce(page([listItem({ id: "r1", query: "newest one" })], 2))
      .mockResolvedValueOnce({
        total: 2,
        limit: 20,
        offset: 1,
        runs: [listItem({ id: "r0", query: "older one" })],
      });

    render(<HistoryPage />);

    expect(await screen.findByText("newest one")).toBeInTheDocument();
    expect(api.listResearch).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /show older research \(1 more\)/i }));

    expect(await screen.findByText("older one")).toBeInTheDocument();
    expect(screen.getByText("newest one")).toBeInTheDocument();
    expect(api.listResearch).toHaveBeenLastCalledWith(20, 1);
    // Everything is listed, so there is nothing left to ask for.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /show older/i })).not.toBeInTheDocument()
    );
  });
});
