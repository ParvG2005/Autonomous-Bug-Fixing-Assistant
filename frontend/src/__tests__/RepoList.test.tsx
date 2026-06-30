import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { RepoList } from "../components/RepoList";
import * as api from "../api";

afterEach(() => vi.restoreAllMocks());

it("lists repos and adds one", async () => {
  vi.spyOn(api, "listRepos").mockResolvedValue([
    { id: "r1", full_name: "octo/demo", publish_capable: false, created_at: "" },
  ]);
  const add = vi
    .spyOn(api, "addRepo")
    .mockResolvedValue({ id: "r2", full_name: "octo/new", publish_capable: false, created_at: "" });
  render(<RepoList />);
  await screen.findByText("octo/demo");
  await userEvent.type(screen.getByPlaceholderText(/github.com/i), "octo/new");
  await userEvent.click(screen.getByRole("button", { name: /add repo/i }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("octo/new"));
});

it("hides the Connect button for a publish-capable repo", async () => {
  vi.spyOn(api, "listRepos").mockResolvedValue([
    { id: "r1", full_name: "octo/capable", publish_capable: true, created_at: "" },
  ]);
  render(<RepoList />);
  await screen.findByText("octo/capable");
  expect(screen.queryByRole("button", { name: /connect/i })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /scan/i })).toBeInTheDocument();
});
