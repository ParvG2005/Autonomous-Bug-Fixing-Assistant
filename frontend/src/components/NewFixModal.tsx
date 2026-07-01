import { useEffect, useState } from "react";
import { createJob, listRepos } from "../api";
import type { Job, Repo } from "../types";

export function NewFixModal({
  onCreated,
  onClose,
}: {
  onCreated: (job: Job) => void;
  onClose: () => void;
}) {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState("");
  const [body, setBody] = useState("");
  const [title, setTitle] = useState("");
  const [ref, setRef] = useState("");
  const [prNumber, setPrNumber] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listRepos().then((rs) => {
      setRepos(rs);
      if (rs[0]) setRepoId(rs[0].id);
    });
  }, []);

  const submit = async () => {
    if (!repoId || !body.trim()) {
      setError("pick a repo and enter issue text");
      return;
    }
    try {
      onCreated(
        await createJob(repoId, body, title, {
          ref: ref || undefined,
          prNumber: prNumber ? Number(prNumber) : undefined,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "submit failed");
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-black/30" role="dialog">
      <div className="w-[32rem] rounded bg-white p-6 shadow-lg">
        <h2 className="mb-3 text-lg font-bold">New Fix</h2>
        <select
          value={repoId}
          onChange={(e) => setRepoId(e.target.value)}
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        >
          {repos.map((r) => (
            <option key={r.id} value={r.id}>
              {r.full_name}
            </option>
          ))}
        </select>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="title (optional)"
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="issue text or stack trace"
          rows={8}
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
        />
        <input
          value={ref}
          onChange={(e) => setRef(e.target.value)}
          placeholder="branch / tag / sha (optional)"
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <input
          type="number"
          min={1}
          step={1}
          value={prNumber}
          onChange={(e) => setPrNumber(e.target.value)}
          placeholder="PR # (GitHub only, optional)"
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        {error && <p className="mb-2 text-sm text-rose-700">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded bg-slate-100 px-3 py-1 text-sm">
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            className="rounded bg-slate-800 px-3 py-1 text-sm font-medium text-white"
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
