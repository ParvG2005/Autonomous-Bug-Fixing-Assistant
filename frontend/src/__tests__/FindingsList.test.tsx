import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FindingsList } from "../components/FindingsList";
import type { Finding } from "../types";

vi.mock("../api", () => ({
  listFindings: vi.fn(),
  promoteFinding: vi.fn(),
}));

import { listFindings, promoteFinding } from "../api";

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: "f-1",
    scan_id: "s-1",
    source: "static",
    summary: "None deref on unexercised path",
    severity: "medium",
    confidence: 0.45,
    status: "candidate",
    job_id: null,
    created_at: "2026-06-30T00:00:00Z",
    ...overrides,
  };
}

afterEach(() => vi.clearAllMocks());

describe("FindingsList", () => {
  it("lists findings and promotes a candidate", async () => {
    vi.mocked(listFindings).mockResolvedValue([makeFinding()]);
    vi.mocked(promoteFinding).mockResolvedValue(makeFinding({ status: "promoted", job_id: "j-1" }));

    render(<FindingsList />);
    await waitFor(() => screen.getByText(/None deref/));

    await userEvent.click(screen.getByRole("button", { name: /promote to job/i }));
    await waitFor(() => expect(promoteFinding).toHaveBeenCalledWith("f-1"));
  });

  it("shows an empty state when there are no findings", async () => {
    vi.mocked(listFindings).mockResolvedValue([]);
    render(<FindingsList />);
    await waitFor(() => screen.getByText(/no findings yet/i));
  });
});
