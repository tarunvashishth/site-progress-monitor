import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/app-shell";
import { ProjectCard } from "@/components/project-card";
import Projects from "@/app/admin/projects/page";
import ClientHome from "@/app/client/page";

const apiMock = vi.fn();
let failNext = false; // plain (non-spy) rejection: vitest spies record returned promises and flag rejections as unhandled
vi.mock("@/lib/api", () => ({ api: (...a: unknown[]) => (failNext ? new Promise((_, rej) => setTimeout(() => rej(new Error("Boom")), 0)) : apiMock(...a)) }));
vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({ auth: { signOut: vi.fn() } }) }));

const proj = { id: "p1", name: "Tower A", location: "Pune", status: "active", start_date: null, overall_progress: 42.5, latest_report: null };

describe("role-specific navigation", () => {
  it("shows admin links to admins only", () => {
    render(<AppShell me={{ id: "1", email: "a@x.com", full_name: "Ann", role: "admin" }}>x</AppShell>);
    expect(screen.getByRole("link", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "My projects" })).toBeNull();
  });
  it("shows only client navigation to clients", () => {
    render(<AppShell me={{ id: "2", email: "c@x.com", full_name: "", role: "client" }}>x</AppShell>);
    expect(screen.getByRole("link", { name: "My projects" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Projects" })).toBeNull();
    expect(screen.getByText("c@x.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
  });
});

describe("project list", () => {
  beforeEach(() => { apiMock.mockReset(); failNext = false; });
  it("renders a project card with progress", () => {
    render(<ProjectCard p={proj} href="/admin/projects/p1" />);
    expect(screen.getByText("Tower A")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42.5");
    expect(screen.getByText("No published report yet")).toBeInTheDocument();
  });
  it("loads, then lists projects from the API", async () => {
    apiMock.mockResolvedValue({ items: [proj], total: 1, limit: 50, offset: 0 });
    render(<Projects />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await screen.findByText("Tower A")).toBeInTheDocument();
  });
  it("shows empty and error states", async () => {
    apiMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    const { unmount } = render(<ClientHome />);
    expect(await screen.findByText("No projects assigned")).toBeInTheDocument();
    unmount();
    failNext = true;
    render(<ClientHome />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Boom"));
  });
});
