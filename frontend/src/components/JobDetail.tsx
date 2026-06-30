import { useEffect, useState } from "react";
import { approveJob, getArtifact, rejectJob } from "../api";
import { useJobStream } from "../hooks/useJobStream";
import type { Job } from "../types";
import { DiffView } from "./DiffView";
import { StatusBadge } from "./StatusBadge";

interface Props {
  job: Job;
  /** Called with the updated job after an approve/reject succeeds. */
  onDecision: (updated: Job) => void;
}

export function JobDetail({ job, onDecision }: Props) {
  const { logs, finalState, error } = useJobStream(job.id);
  const [diff, setDiff] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState<string | null>(null);
  const [actor, setActor] = useState("dashboard");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Re-fetch artifacts whenever the job (or its stream's terminal state) changes.
  useEffect(() => {
    let live = true;
    getArtifact(job.id, "diff")
      .then((a) => live && setDiff(a.content))
      .catch(() => live && setDiff(null));
    getArtifact(job.id, "reasoning")
      .then((a) => live && setReasoning(a.content))
      .catch(() => live && setReasoning(null));
    return () => {
      live = false;
    };
  }, [job.id, finalState]);

  const canDecide = job.state === "awaiting_approval";

  async function decide(kind: "approve" | "reject") {
    setBusy(true);
    setActionError(null);
    try {
      const fn = kind === "approve" ? approveJob : rejectJob;
      const updated = await fn(job.id, actor.trim() || "dashboard");
      onDecision(updated);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{job.issue_title ?? "(untitled issue)"}</h2>
          <p className="text-xs text-slate-500">
            {job.id} · ${job.cost_usd.toFixed(3)}
          </p>
        </div>
        <StatusBadge state={job.state} />
      </header>

      {job.failure_reason && (
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">{job.failure_reason}</p>
      )}

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-600">Phases</h3>
        <div className="flex flex-wrap gap-2">
          {job.runs.map((r, i) => (
            <span
              key={i}
              className="rounded border border-slate-200 bg-white px-2 py-1 text-xs"
              title={r.status}
            >
              {r.phase}: <span className="font-medium">{r.status}</span>
            </span>
          ))}
          {job.runs.length === 0 && <span className="text-xs text-slate-400">no runs yet</span>}
        </div>
      </section>

      {job.fix && (
        <section className="text-sm">
          <h3 className="mb-1 text-sm font-semibold text-slate-600">Proposed fix</h3>
          <p className="text-xs text-slate-500">
            +{job.fix.diff_lines_added} −{job.fix.diff_lines_removed} ·{" "}
            {job.fix.wrote_repro_test ? "wrote a reproduction test · " : ""}
            tests {job.fix.tests_pass ? "pass" : "fail"}
          </p>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-600">Live log</h3>
        <pre className="max-h-56 overflow-auto rounded-md bg-ink p-3 text-xs text-slate-100">
          {logs.length ? logs.join("\n") : "waiting for output…"}
        </pre>
        {error && <p className="mt-1 text-xs text-amber-600">{error}</p>}
      </section>

      {diff && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-600">Diff</h3>
          <DiffView diff={diff} />
        </section>
      )}

      {reasoning && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-600">Reasoning</h3>
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-700">
            {reasoning}
          </pre>
        </section>
      )}

      {canDecide && (
        <section className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4">
          <label className="text-xs text-slate-500">
            actor{" "}
            <input
              aria-label="actor"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => decide("approve")}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => decide("reject")}
            className="rounded-md bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          >
            Reject
          </button>
          {actionError && <span className="text-xs text-rose-600">{actionError}</span>}
        </section>
      )}
    </div>
  );
}
