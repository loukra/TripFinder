// Mirrors backend/src/tripfinder/api/schemas.py and domain/models.py (plan §11).
// The API exposes domain concepts only, so these types are the frontend's
// only picture of a research run — nothing here should drift from the DTOs.

export type ResearchStatus =
  | "pending"
  | "understanding"
  | "needs_clarification"
  | "rejected"
  | "discovering"
  | "retrieving"
  | "analyzing"
  | "aggregating"
  | "completed"
  | "completed_partial"
  | "completed_degraded"
  | "source_unavailable"
  | "failed"
  | "cancelled";

// Matches the backend's HALTING_STATUSES ∪ the completed_* family (domain/models.py):
// every status from which the pipeline will not advance on its own, so polling
// should stop. `needs_clarification` belongs here even though the research can
// later resume — nothing changes until the user answers.
export const STOP_POLLING_STATUSES: ReadonlySet<ResearchStatus> = new Set([
  "needs_clarification",
  "rejected",
  "completed",
  "completed_partial",
  "completed_degraded",
  "source_unavailable",
  "failed",
  "cancelled",
]);

export const RESULTS_READY_STATUSES: ReadonlySet<ResearchStatus> = new Set([
  "completed",
  "completed_partial",
  "completed_degraded",
]);

// Statuses whose results object is unfinished (plan §2.13.3). `analyzing` is a
// run still reading; `cancelled` is the same corpus frozen where the user
// stopped it, and serves a results object only if it got far enough to have
// one — so a fetch for either may legitimately come back 409 and must not be
// treated as an error.
export const PROVISIONAL_STATUSES: ReadonlySet<ResearchStatus> = new Set([
  "analyzing",
  "cancelled",
]);

export const RESULTS_AVAILABLE_STATUSES: ReadonlySet<ResearchStatus> = new Set([
  ...RESULTS_READY_STATUSES,
  ...PROVISIONAL_STATUSES,
]);

export const CANCELLABLE_STATUSES: ReadonlySet<ResearchStatus> = new Set([
  "pending",
  "understanding",
  "needs_clarification",
  "discovering",
  "retrieving",
  "analyzing",
  "aggregating",
]);

export type EntityType =
  | "country"
  | "region"
  | "state"
  | "city"
  | "town"
  | "park"
  | "beach"
  | "trail"
  | "island"
  | "other";

export interface ClarificationOption {
  label: string;
  entity_granularity: EntityType;
}

export interface ClarificationRequest {
  question: string;
  options: ClarificationOption[];
  allow_grouped: boolean;
}

export interface SourceHealth {
  adapter: string;
  calls_attempted: number;
  calls_succeeded: number;
  calls_failed: number;
  failure_kinds: Record<string, number>;
  success_rate: number;
}

export interface Suppression {
  step: string;
  reason: string;
  count: number;
  detail: string | null;
}

export type ResearchFlag = "low_polling_document_ratio" | "budget_limit_reached";

export interface ResearchFailure {
  kind: string;
  step: string;
  detail: string;
}

export interface ResearchDiagnostics {
  source_health: SourceHealth[];
  source_outcome: "healthy" | "degraded" | "unavailable" | null;
  suppressions: Suppression[];
  flags: ResearchFlag[];
  failure: ResearchFailure | null;
}

export interface ResearchCreateResponse {
  id: string;
  status: ResearchStatus;
}

export interface ClarifyResponse {
  id: string;
  status: ResearchStatus;
}

export interface ResearchStatusResponse {
  id: string;
  status: ResearchStatus;
  message: string;
  statistics: Record<string, number>;
  diagnostics: ResearchDiagnostics;
  clarification: ClarificationRequest | null;
}

export interface ResultItem {
  entity_id: string;
  entity_name: string;
  supporter_count: number;
  share: number | null;
  respondent_pool_size: number;
  discussion_count: number;
  weighted_score: number;
  confidence: number;
  explanation: string | null;
  evidence_permalinks: string[];
}

export interface ResearchResultsResponse {
  id: string;
  status: ResearchStatus;
  message: string;
  percentages_suppressed: boolean;
  // Whether this ranking is still growing (plan §2.13). A provisional
  // response is also recognisable without this flag — every `share` is null —
  // which is the point: a client that ignores it cannot show a percentage.
  provisional: boolean;
  results: ResultItem[];
  // Everything ranked below the strong line. Early in a run this is where all
  // the evidence is, because nobody has five supporters yet and §4.4 forbids
  // padding the strong list to hide that.
  weak_results: ResultItem[];
}

export interface EvidenceResponse {
  entity_id: string;
  entity_name: string;
  total: number;
  limit: number;
  offset: number;
  permalinks: string[];
}
