import { useCallback, useEffect, useState } from "react";
import { addRepo, connectRepo, deleteRepo, listRepos, scanRepo } from "../api";
import type { Repo } from "../types";

export function RepoList() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRepos(await listRepos());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load repos");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onAdd = async () => {
    if (!url.trim()) return;
    try {
      await addRepo(url.trim());
      setUrl("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "add failed");
    }
  };

  // Scan/Connect enqueue async worker tasks (HTTP 202) — await so failures
  // surface instead of becoming unhandled rejections, then refresh because a
  // successful connect flips publish_capable (and hides its own button).
  const onTask = async (
    key: string,
    label: string,
    fn: () => Promise<unknown>,
    okMessage: string,
  ) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(okMessage);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${label} failed`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="p-6">
      <div className="mb-4 flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/name, a git URL, or local path"
          className="flex-1 rounded border border-slate-300 px-3 py-1 text-sm"
        />
        <button
          type="button"
          onClick={onAdd}
          className="rounded bg-slate-800 px-3 py-1 text-sm font-medium text-white"
        >
          Add repo
        </button>
      </div>
      {error && <p className="mb-2 text-sm text-rose-700">{error}</p>}
      {notice && <p className="mb-2 text-sm text-emerald-700">{notice}</p>}
      <ul className="divide-y divide-slate-200">
        {repos.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-2">
            <span className="text-sm font-medium">{r.full_name}</span>
            <span className="flex items-center gap-2 text-xs">
              <span className={r.publish_capable ? "text-emerald-600" : "text-slate-400"}>
                {r.publish_capable ? "publish-capable" : "fix-only"}
              </span>
              <button
                type="button"
                disabled={busy === `scan:${r.id}`}
                onClick={() => onTask(`scan:${r.id}`, "Scan", () => scanRepo(r.id), "Scan started")}
                className="rounded bg-slate-100 px-2 py-1 disabled:opacity-50"
              >
                Scan
              </button>
              {!r.publish_capable && (
                <button
                  type="button"
                  disabled={busy === `connect:${r.id}`}
                  onClick={() =>
                    onTask(
                      `connect:${r.id}`,
                      "Connect GitHub App",
                      () => connectRepo(r.id),
                      "Connecting GitHub App",
                    )
                  }
                  className="rounded bg-slate-100 px-2 py-1 disabled:opacity-50"
                >
                  Connect GitHub App
                </button>
              )}
              <button
                type="button"
                disabled={busy === `delete:${r.id}`}
                onClick={() => onTask(`delete:${r.id}`, "Delete", () => deleteRepo(r.id), "Repo deleted")}
                className="rounded bg-rose-50 px-2 py-1 text-rose-700 disabled:opacity-50"
              >
                Delete
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
