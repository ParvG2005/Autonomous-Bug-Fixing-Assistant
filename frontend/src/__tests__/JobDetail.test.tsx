import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobDetail } from "../components/JobDetail";
import type { Job } from "../types";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    approveJob: vi.fn(),
    rejectJob: vi.fn(),
    getArtifact: vi.fn().mockRejectedValue(new Error("none")),
  };
});

import { approveJob, rejectJob } from "../api";

class NoopEventSource {
  addEventListener() {}
  close() {}
  constructor(public url: string) {}
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    state: "awaiting_approval",
    gh_issue_number: 7,
    issue_title: "boom",
    failure_reason: null,
    cost: {},
    cost_usd: 0.05,
    created_at: "2026-06-30T00:00:00Z",
    updated_at: "2026-06-30T00:00:00Z",
    runs: [{ phase: "fix", status: "ok", attempt: 1, metrics: {} }],
    fix: {
      diff_lines_added: 3,
      diff_lines_removed: 1,
      wrote_repro_test: true,
      tests_pass: true,
      flags: {},
    },
    ...overrides,
  };
}

beforeEach(() => vi.stubGlobal("EventSource", NoopEventSource));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("JobDetail", () => {
  it("approves and reports the updated job", async () => {
    const updated = makeJob({ state: "approved" });
    vi.mocked(approveJob).mockResolvedValue(updated);
    const onDecision = vi.fn();

    render(<JobDetail job={makeJob()} onDecision={onDecision} />);
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));

    await waitFor(() => expect(onDecision).toHaveBeenCalledWith(updated));
    expect(approveJob).toHaveBeenCalledWith("job-1", "dashboard");
  });

  it("rejects with the typed actor", async () => {
    vi.mocked(rejectJob).mockResolvedValue(makeJob({ state: "rejected" }));
    const onDecision = vi.fn();

    render(<JobDetail job={makeJob()} onDecision={onDecision} />);
    const actor = screen.getByLabelText("actor");
    await userEvent.clear(actor);
    await userEvent.type(actor, "parv");
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));

    await waitFor(() => expect(rejectJob).toHaveBeenCalledWith("job-1", "parv"));
  });

  it("hides the approve/reject controls when the job is not awaiting approval", async () => {
    render(<JobDetail job={makeJob({ state: "running" })} onDecision={vi.fn()} />);
    // let the pending artifact fetches settle so no state update escapes act()
    await waitFor(() => expect(screen.getByText("Live log")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
  });

  it("surfaces a server error without calling onDecision", async () => {
    vi.mocked(approveJob).mockRejectedValue(new Error("job is 'running'"));
    const onDecision = vi.fn();
    render(<JobDetail job={makeJob()} onDecision={onDecision} />);
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    await waitFor(() => expect(screen.getByText(/job is 'running'/)).toBeInTheDocument());
    expect(onDecision).not.toHaveBeenCalled();
  });
});
