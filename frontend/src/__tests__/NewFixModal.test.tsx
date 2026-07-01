import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { NewFixModal } from "../components/NewFixModal";
import * as api from "../api";

afterEach(() => vi.restoreAllMocks());

it("submits a new fix", async () => {
  vi.spyOn(api, "listRepos").mockResolvedValue([
    { id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" },
  ]);
  const create = vi.spyOn(api, "createJob").mockResolvedValue({ id: "j1" } as never);
  const onCreated = vi.fn();
  render(<NewFixModal onCreated={onCreated} onClose={() => {}} />);
  await screen.findByText("octo/demo");
  await userEvent.type(screen.getByPlaceholderText(/issue text/i), "boom");
  await userEvent.click(screen.getByRole("button", { name: /submit/i }));
  expect(create).toHaveBeenCalledWith("r1", "boom", "", { ref: undefined, prNumber: undefined });
  expect(onCreated).toHaveBeenCalled();
});

it("submits a ref and PR number when provided", async () => {
  vi.spyOn(api, "listRepos").mockResolvedValue([
    { id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" },
  ]);
  const create = vi.spyOn(api, "createJob").mockResolvedValue({ id: "j1" } as never);
  const onCreated = vi.fn();
  render(<NewFixModal onCreated={onCreated} onClose={() => {}} />);
  await screen.findByText("octo/demo");
  await userEvent.type(screen.getByPlaceholderText(/issue text/i), "boom");
  await userEvent.type(screen.getByPlaceholderText(/branch \/ tag \/ sha/i), "feature/x");
  await userEvent.type(screen.getByPlaceholderText(/PR #/i), "12");
  await userEvent.click(screen.getByRole("button", { name: /submit/i }));
  expect(create).toHaveBeenCalledWith("r1", "boom", "", { ref: "feature/x", prNumber: 12 });
  expect(onCreated).toHaveBeenCalled();
});

it("blocks submit and shows an error when issue text is empty", async () => {
  vi.spyOn(api, "listRepos").mockResolvedValue([
    { id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" },
  ]);
  const create = vi.spyOn(api, "createJob").mockResolvedValue({ id: "j1" } as never);
  const onCreated = vi.fn();
  render(<NewFixModal onCreated={onCreated} onClose={() => {}} />);
  await screen.findByText("octo/demo");
  await userEvent.click(screen.getByRole("button", { name: /submit/i }));
  expect(create).not.toHaveBeenCalled();
  expect(onCreated).not.toHaveBeenCalled();
  expect(await screen.findByText(/pick a repo and enter issue text/i)).toBeInTheDocument();
});
