import type { JobState } from "../types";

const STYLES: Record<JobState, string> = {
  queued: "bg-slate-200 text-slate-700",
  running: "bg-blue-100 text-blue-700",
  awaiting_approval: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-rose-100 text-rose-700",
  done: "bg-emerald-600 text-white",
  failed: "bg-rose-600 text-white",
};

export function StatusBadge({ state }: { state: JobState }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${STYLES[state]}`}
    >
      {state.replace(/_/g, " ")}
    </span>
  );
}
