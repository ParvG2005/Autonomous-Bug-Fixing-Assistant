// Thin typed client over the control-plane API. Relative URLs so the same build
// works behind the Vite dev proxy and same-origin in production.

import type { ArtifactKind, ArtifactView, Finding, Job, Repo } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export function listJobs(limit = 50): Promise<Job[]> {
  return request<Job[]>(`/jobs?limit=${limit}`);
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(`/jobs/${id}`);
}

export function getArtifact(id: string, kind: ArtifactKind): Promise<ArtifactView> {
  return request<ArtifactView>(`/jobs/${id}/artifacts/${kind}`);
}

export function approveJob(id: string, actor: string, note?: string): Promise<Job> {
  return request<Job>(`/jobs/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ actor, note }),
  });
}

export function rejectJob(id: string, actor: string, note?: string): Promise<Job> {
  return request<Job>(`/jobs/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ actor, note }),
  });
}

export function logStreamUrl(id: string): string {
  return `/jobs/${id}/logs`;
}

// --- Phase 13: proactive discovery ---

export function listFindings(limit = 100): Promise<Finding[]> {
  return request<Finding[]>(`/findings?limit=${limit}`);
}

/** Promote a finding to a queued discovery job (human gate at discovery). */
export function promoteFinding(id: string): Promise<Finding> {
  return request<Finding>(`/findings/${id}/promote`, { method: "POST" });
}

// --- Repos, manual jobs, publish (UI control plane) ---

export function listRepos(): Promise<Repo[]> {
  return request<Repo[]>("/repos");
}
export function addRepo(cloneUrl: string): Promise<Repo> {
  return request<Repo>("/repos", { method: "POST", body: JSON.stringify({ clone_url: cloneUrl }) });
}
export function deleteRepo(id: string): Promise<void> {
  return request<void>(`/repos/${id}`, { method: "DELETE" });
}
export function connectRepo(id: string): Promise<{ status: string }> {
  return request(`/repos/${id}/connect`, { method: "POST" });
}
export function scanRepo(id: string): Promise<{ status: string }> {
  return request(`/repos/${id}/scan`, { method: "POST" });
}
export function createJob(
  repoId: string,
  body: string,
  title?: string,
  opts?: { ref?: string; prNumber?: number },
): Promise<Job> {
  return request<Job>("/jobs", {
    method: "POST",
    body: JSON.stringify({
      repo_id: repoId,
      body,
      title,
      ref: opts?.ref || undefined,
      pr_number: opts?.prNumber ?? undefined,
    }),
  });
}
export function publishJob(id: string): Promise<{ status: string }> {
  return request(`/jobs/${id}/publish`, { method: "POST" });
}
