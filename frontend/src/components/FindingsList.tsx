import { useCallback, useEffect, useState } from "react";
import { listFindings, promoteFinding } from "../api";
import type { Finding } from "../types";

const SEVERITY_COLOR: Record<string, string> = {
  critical: "bg-rose-100 text-rose-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-slate-100 text-slate-600",
};

const POLL_MS = 5000;

/** The Findings tab: proactive-discovery candidates and a one-click promote. */
export function FindingsList() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setFindings(await listFindings());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load findings");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const onPromote = useCallback(
    async (id: string) => {
      setBusy(id);
      try {
        await promoteFinding(id);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "promote failed");
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  if (findings.length === 0) {
    return <p className="p-6 text-sm text-slate-500">No findings yet. Run a scan.</p>;
  }

  return (
    <div className="p-4">
      {error && <p className="mb-3 rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
      <ul className="divide-y divide-slate-200">
        {findings.map((f) => (
          <li key={f.id} className="flex items-center justify-between gap-3 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{f.summary}</p>
              <p className="text-xs text-slate-500">
                <span
                  className={`mr-2 rounded px-1.5 py-0.5 ${
                    SEVERITY_COLOR[f.severity] ?? SEVERITY_COLOR.low
                  }`}
                >
                  {f.severity}
                </span>
                {f.source} · conf {f.confidence.toFixed(2)} · {f.status}
              </p>
            </div>
            {f.status === "candidate" ? (
              <button
                type="button"
                disabled={busy === f.id}
                onClick={() => void onPromote(f.id)}
                className="shrink-0 rounded bg-slate-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                {busy === f.id ? "Promoting…" : "Promote to job"}
              </button>
            ) : (
              <span className="shrink-0 text-xs text-slate-400">{f.status}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
