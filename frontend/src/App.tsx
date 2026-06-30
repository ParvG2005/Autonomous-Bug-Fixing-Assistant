import { useCallback, useEffect, useState } from "react";
import { getJob, listJobs } from "./api";
import { FindingsList } from "./components/FindingsList";
import { JobDetail } from "./components/JobDetail";
import { JobList } from "./components/JobList";
import { RepoList } from "./components/RepoList";
import type { Job } from "./types";

const POLL_MS = 4000;

type Tab = "jobs" | "findings" | "repos";

const TAB_LABELS: Record<Tab, string> = {
  jobs: "Jobs",
  findings: "Findings",
  repos: "Repos",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("jobs");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      setJobs(await listJobs());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load jobs");
    }
  }, []);

  // Poll the list (the SSE stream covers per-job live logs; the list refresh is
  // a coarse fallback so new jobs and state changes appear without a reload).
  useEffect(() => {
    void refreshJobs();
    const t = setInterval(() => void refreshJobs(), POLL_MS);
    return () => clearInterval(t);
  }, [refreshJobs]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    let live = true;
    getJob(selectedId)
      .then((j) => live && setSelected(j))
      .catch(() => live && setSelected(null));
    return () => {
      live = false;
    };
  }, [selectedId, jobs]);

  const onDecision = useCallback(
    (updated: Job) => {
      setSelected(updated);
      void refreshJobs();
    },
    [refreshJobs],
  );

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <h1 className="text-xl font-bold">Bugfix Assistant</h1>
        <p className="text-xs text-slate-500">Watch a fix live and approve it.</p>
        <nav className="mt-3 flex gap-2" role="tablist">
          {(["jobs", "findings", "repos"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`rounded px-3 py-1 text-sm font-medium ${
                tab === t ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"
              }`}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </nav>
      </header>
      {error && <p className="bg-rose-50 px-6 py-2 text-sm text-rose-700">{error}</p>}
      {tab === "repos" ? (
        <main className="flex-1 bg-white">
          <RepoList />
        </main>
      ) : tab === "findings" ? (
        <main className="flex-1 bg-white">
          <FindingsList />
        </main>
      ) : (
        <div className="grid flex-1 grid-cols-1 md:grid-cols-[20rem_1fr]">
          <aside className="border-r border-slate-200 bg-white">
            <JobList jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} />
          </aside>
          <main>
            {selected ? (
              <JobDetail key={selected.id} job={selected} onDecision={onDecision} />
            ) : (
              <p className="p-6 text-sm text-slate-500">Select a job to see its details.</p>
            )}
          </main>
        </div>
      )}
    </div>
  );
}
