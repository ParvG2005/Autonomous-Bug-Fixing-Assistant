import { afterEach, describe, expect, it, vi } from "vitest";
import { approveJob, getArtifact, getJob, listJobs, rejectJob } from "../api";
import { addRepo, createJob, deleteRepo } from "../api";

function mockFetch(body: unknown, ok = true, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: "x",
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("listJobs requests /jobs with a limit and returns the array", async () => {
    const fetchMock = mockFetch([{ id: "a" }]);
    const jobs = await listJobs(10);
    expect(fetchMock).toHaveBeenCalledWith("/jobs?limit=10", expect.anything());
    expect(jobs).toEqual([{ id: "a" }]);
  });

  it("getJob requests the job by id", async () => {
    const fetchMock = mockFetch({ id: "abc" });
    const job = await getJob("abc");
    expect(fetchMock).toHaveBeenCalledWith("/jobs/abc", expect.anything());
    expect(job.id).toBe("abc");
  });

  it("approveJob POSTs the actor to the approve route", async () => {
    const fetchMock = mockFetch({ id: "abc", state: "approved" });
    const job = await approveJob("abc", "parv", "lgtm");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/jobs/abc/approve");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ actor: "parv", note: "lgtm" });
    expect(job.state).toBe("approved");
  });

  it("rejectJob POSTs to the reject route", async () => {
    const fetchMock = mockFetch({ id: "abc", state: "rejected" });
    await rejectJob("abc", "parv");
    expect(fetchMock.mock.calls[0][0]).toBe("/jobs/abc/reject");
  });

  it("getArtifact fetches the kind body", async () => {
    const fetchMock = mockFetch({ kind: "diff", content: "--- a" });
    const art = await getArtifact("abc", "diff");
    expect(fetchMock.mock.calls[0][0]).toBe("/jobs/abc/artifacts/diff");
    expect(art.content).toBe("--- a");
  });

  it("throws ApiError carrying the server detail on a non-2xx", async () => {
    mockFetch({ detail: "job is 'running'; only an awaiting_approval job can be decided" }, false, 409);
    await expect(approveJob("abc", "parv")).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
    });
  });

  it("addRepo posts clone_url", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" }),
        { status: 201, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const repo = await addRepo("octo/demo");
    expect(repo.full_name).toBe("octo/demo");
    expect(fetchMock).toHaveBeenCalledWith("/repos", expect.objectContaining({ method: "POST" }));
  });

  it("deleteRepo handles a 204 response without throwing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(deleteRepo("r1")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith("/repos/r1", expect.objectContaining({ method: "DELETE" }));
  });

  it("createJob posts repo_id, body, and title", async () => {
    const fetchMock = mockFetch({ id: "j1", state: "queued" });
    await createJob("repo1", "steps to repro", "Bug title");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/jobs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ repo_id: "repo1", body: "steps to repro", title: "Bug title" });
  });
});
