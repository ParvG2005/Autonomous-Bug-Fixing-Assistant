// Mirrors the Pydantic views in app/api/jobs.py. Kept hand-written (small,
// stable surface) rather than codegen'd.

export type JobState =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "done"
  | "failed";

export interface RunView {
  phase: string;
  status: string;
  attempt: number;
  metrics: Record<string, unknown>;
}

export interface FixView {
  diff_lines_added: number;
  diff_lines_removed: number;
  wrote_repro_test: boolean;
  tests_pass: boolean;
  flags: Record<string, unknown>;
}

export interface Job {
  id: string;
  state: JobState;
  gh_issue_number: number | null;
  issue_title: string | null;
  failure_reason: string | null;
  cost: Record<string, unknown>;
  cost_usd: number;
  created_at: string;
  updated_at: string;
  runs: RunView[];
  fix: FixView | null;
  repo_full_name: string;
  publish_capable: boolean;
}

export type ArtifactKind = "diff" | "reasoning" | "trace";

export interface ArtifactView {
  kind: string;
  content: string;
}

// --- Phase 13: proactive discovery ---
export type FindingStatus =
  | "candidate"
  | "reproduced"
  | "promoted"
  | "dismissed"
  | "duplicate";

/** Mirrors FindingView in app/api/findings.py. */
export interface Finding {
  id: string;
  scan_id: string;
  source: string;
  summary: string;
  severity: string;
  confidence: number;
  status: FindingStatus;
  job_id: string | null;
  created_at: string;
}

/** Mirrors RepoView in app/api/repos.py. */
export interface Repo {
  id: string;
  full_name: string;
  publish_capable: boolean;
  created_at: string;
}

/** A job state is terminal (or awaiting a decision) when no log stream remains open. */
export const STREAM_CLOSED_STATES: ReadonlySet<JobState> = new Set<JobState>([
  "awaiting_approval",
  "approved",
  "rejected",
  "done",
  "failed",
]);
