// Subscribes to the job's SSE log stream (GET /jobs/{id}/logs). The server
// emits `log` events (one progress line each) and a terminal `state` event,
// then closes. We collect log lines and surface the final state so the UI can
// re-fetch the job (e.g. to reveal the approve/reject buttons).

import { useEffect, useRef, useState } from "react";
import { logStreamUrl } from "../api";
import type { JobState } from "../types";

export interface JobStream {
  logs: string[];
  finalState: JobState | null;
  error: string | null;
}

export function useJobStream(jobId: string | null): JobStream {
  const [logs, setLogs] = useState<string[]>([]);
  const [finalState, setFinalState] = useState<JobState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!jobId) return;
    setLogs([]);
    setFinalState(null);
    setError(null);

    const source = new EventSource(logStreamUrl(jobId));
    sourceRef.current = source;

    source.addEventListener("log", (e) => {
      const { message } = JSON.parse((e as MessageEvent).data) as { message: string };
      setLogs((prev) => [...prev, message]);
    });
    source.addEventListener("state", (e) => {
      const { state } = JSON.parse((e as MessageEvent).data) as { state: JobState };
      setFinalState(state);
      source.close();
    });
    source.addEventListener("error", () => {
      // EventSource fires `error` on close too; only surface it if we never
      // reached a terminal state.
      setError((prev) => prev ?? "log stream interrupted");
    });

    return () => source.close();
  }, [jobId]);

  return { logs, finalState, error };
}
