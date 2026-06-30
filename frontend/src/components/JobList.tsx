import type { Job } from "../types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  jobs: Job[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function JobList({ jobs, selectedId, onSelect }: Props) {
  if (jobs.length === 0) {
    return <p className="p-4 text-sm text-slate-500">No jobs yet.</p>;
  }
  return (
    <ul className="divide-y divide-slate-200">
      {jobs.map((job) => (
        <li key={job.id}>
          <button
            type="button"
            onClick={() => onSelect(job.id)}
            className={`flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-slate-100 ${
              job.id === selectedId ? "bg-slate-100" : ""
            }`}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium">
                {job.issue_title ?? "(untitled issue)"}
              </span>
              <StatusBadge state={job.state} />
            </span>
            <span className="text-xs text-slate-500">
              {job.gh_issue_number ? `#${job.gh_issue_number} · ` : ""}
              {new Date(job.created_at).toLocaleString()}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
