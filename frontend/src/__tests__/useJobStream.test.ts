import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useJobStream } from "../hooks/useJobStream";

type Listener = (e: { data: string }) => void;

// Minimal controllable EventSource standing in for the browser's. Tests grab
// the latest instance and push events through it.
class MockEventSource {
  static last: MockEventSource | null = null;
  listeners: Record<string, Listener[]> = {};
  closed = false;
  constructor(public url: string) {
    MockEventSource.last = this;
  }
  addEventListener(type: string, cb: Listener) {
    (this.listeners[type] ??= []).push(cb);
  }
  emit(type: string, data: unknown) {
    for (const cb of this.listeners[type] ?? []) cb({ data: JSON.stringify(data) });
  }
  close() {
    this.closed = true;
  }
}

afterEach(() => vi.unstubAllGlobals());

describe("useJobStream", () => {
  it("collects log lines and captures the terminal state", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const { result } = renderHook(() => useJobStream("job-1"));
    const src = MockEventSource.last!;
    expect(src.url).toBe("/jobs/job-1/logs");

    act(() => {
      src.emit("log", { message: "cloning repo" });
      src.emit("log", { message: "fix verified" });
      src.emit("state", { state: "awaiting_approval" });
    });

    await waitFor(() => expect(result.current.finalState).toBe("awaiting_approval"));
    expect(result.current.logs).toEqual(["cloning repo", "fix verified"]);
    expect(src.closed).toBe(true);
  });

  it("does not open a stream for a null job id", () => {
    vi.stubGlobal("EventSource", MockEventSource);
    MockEventSource.last = null;
    renderHook(() => useJobStream(null));
    expect(MockEventSource.last).toBeNull();
  });
});
