// Thin typed client over the control-plane API. Relative URLs so the same build
// works behind the Vite dev proxy and same-origin in production.

import type { ArtifactKind, ArtifactView, Job } from "./types";

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
