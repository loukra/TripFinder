import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvidencePanel } from "./EvidencePanel";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof api>("@/lib/api");
  return { ...actual, getEvidence: vi.fn() };
});

describe("EvidencePanel", () => {
  it("loads on mount and paginates evidence links", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getEvidence)
      .mockResolvedValueOnce({
        entity_id: "state:alaska",
        entity_name: "Alaska",
        total: 2,
        limit: 1,
        offset: 0,
        permalinks: ["https://reddit.com/a"],
      })
      .mockResolvedValueOnce({
        entity_id: "state:alaska",
        entity_name: "Alaska",
        total: 2,
        limit: 1,
        offset: 1,
        permalinks: ["https://reddit.com/b"],
      });

    render(<EvidencePanel researchId="r1" entityId="state:alaska" entityName="Alaska" />);

    expect(await screen.findByText("https://reddit.com/a")).toBeInTheDocument();
    expect(api.getEvidence).toHaveBeenCalledWith("r1", "state:alaska", 10, 0);

    const loadMore = await screen.findByRole("button", { name: "Load more" });
    await user.click(loadMore);

    expect(await screen.findByText("https://reddit.com/b")).toBeInTheDocument();
    expect(screen.getByText("https://reddit.com/a")).toBeInTheDocument();
  });

  it("shows an empty state when there is no evidence", async () => {
    vi.mocked(api.getEvidence).mockResolvedValue({
      entity_id: "state:alaska",
      entity_name: "Alaska",
      total: 0,
      limit: 10,
      offset: 0,
      permalinks: [],
    });

    render(<EvidencePanel researchId="r1" entityId="state:alaska" entityName="Alaska" />);

    expect(await screen.findByText(/no evidence links were retained/i)).toBeInTheDocument();
  });

  it("shows an error if the evidence request fails", async () => {
    vi.mocked(api.getEvidence).mockRejectedValue(new api.ApiError(500, { message: "server error" }));

    render(<EvidencePanel researchId="r1" entityId="state:alaska" entityName="Alaska" />);

    expect(await screen.findByText("server error")).toBeInTheDocument();
  });
});
