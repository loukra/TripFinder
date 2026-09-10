import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DiagnosticsSummary } from "./DiagnosticsSummary";
import type { ResearchDiagnostics } from "@/lib/types";

describe("DiagnosticsSummary", () => {
  it("renders nothing when there is nothing to disclose", () => {
    const diagnostics: ResearchDiagnostics = {
      source_health: [],
      source_outcome: null,
      suppressions: [],
      flags: [],
      failure: null,
    };

    const { container } = render(<DiagnosticsSummary diagnostics={diagnostics} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("surfaces suppression counts, flags, and source health", () => {
    const diagnostics: ResearchDiagnostics = {
      source_health: [
        {
          adapter: "arctic_shift",
          calls_attempted: 40,
          calls_succeeded: 20,
          calls_failed: 20,
          failure_kinds: { timeout: 20 },
          success_rate: 0.5,
        },
      ],
      source_outcome: "degraded",
      suppressions: [{ step: "triage", reason: "triage_excluded", count: 12, detail: null }],
      flags: ["low_polling_document_ratio"],
      failure: null,
    };

    render(<DiagnosticsSummary diagnostics={diagnostics} />);

    expect(screen.getByText(/few of the discussions found were open questions/i)).toBeInTheDocument();
    expect(screen.getByText("arctic_shift")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("triage")).toBeInTheDocument();
    expect(screen.getByText("triage excluded")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });
});
