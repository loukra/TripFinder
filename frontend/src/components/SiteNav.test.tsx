import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SiteNav } from "./SiteNav";

let pathname = "/";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

describe("SiteNav", () => {
  it("offers a way back to a new search from a run", () => {
    pathname = "/research/r1";
    render(<SiteNav />);

    expect(screen.getByRole("link", { name: "New research" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute("href", "/history");
  });

  // On the search page the link would lead to where the user already is.
  it("leaves it out on the search page itself", () => {
    pathname = "/";
    render(<SiteNav />);

    expect(screen.queryByRole("link", { name: "New research" })).not.toBeInTheDocument();
  });
});
