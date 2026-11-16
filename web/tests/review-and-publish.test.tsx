import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ObservationCard } from "@/components/observation-card";
import { DraftEditor } from "@/app/admin/reports/[id]/page";
import type { Observation, Report } from "@/lib/types";

const apiMock = vi.fn();
vi.mock("@/lib/api", () => ({ api: (...a: unknown[]) => apiMock(...a) }));

const obs: Observation = { id: "o1", title: "Slab work", description: "Crew pouring", category: "concrete", observation_type: "ongoing",
  confidence: 0.9, review_status: "pending", evidence: [{ frame_id: "f1", frame_index: 0, timestamp_seconds: 12, thumb_url: "http://x/t.jpg" }] };

describe("AI observation review", () => {
  beforeEach(() => { apiMock.mockReset(); apiMock.mockResolvedValue({}); });
  it("approves with one click", async () => {
    const changed = vi.fn();
    render(<ObservationCard o={obs} onChanged={changed} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(apiMock).toHaveBeenCalledWith("/observations/o1", { method: "PATCH", json: { review_status: "approved" } });
    await waitFor(() => expect(changed).toHaveBeenCalled());
  });
  it("asks for confirmation before rejecting", async () => {
    render(<ObservationCard o={obs} onChanged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(apiMock).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Reject", hidden: false, description: undefined }).catch(() => screen.getAllByRole("button", { name: "Reject" }).at(-1)!));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/observations/o1", { method: "PATCH", json: { review_status: "rejected" } }));
  });
  it("edits the text and sends only the changed fields", async () => {
    render(<ObservationCard o={obs} onChanged={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit text" }));
    const d = screen.getByLabelText("Description");
    await userEvent.clear(d); await userEvent.type(d, "Level 1 slab being poured");
    await userEvent.click(screen.getByRole("button", { name: "Save text" }));
    expect(apiMock).toHaveBeenCalledWith("/observations/o1", { method: "PATCH", json: { title: "Slab work", description: "Level 1 slab being poured" } });
  });
  it("shows no actions when the report is published", () => {
    render(<ObservationCard o={obs} onChanged={vi.fn()} locked />);
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

const draft = (o: Partial<Report> = {}): Report => ({
  id: "r1", project_id: "p", video_id: "v", status: "draft", summary: "Slab poured.", capture_date: "2026-03-02", published_at: null,
  overall_progress_percentage: 30, assessment_coverage_percentage: 0, retained_package_count: 2, video_url: "http://v",
  work_packages: [
    { work_package_id: "w1", name: "Foundation", weight_percentage: 60, previous_approved_percentage: 50, approved_percentage: null, assessed: false, decision: "pending",
      ai: { assessable: true, proposed_completion_percentage: 70, confidence: 0.8, reasoning: "slab visible" } },
    { work_package_id: "w2", name: "Roof", weight_percentage: 40, previous_approved_percentage: 0, approved_percentage: 0, assessed: false, decision: "retain",
      ai: { assessable: false, proposed_completion_percentage: null, confidence: 0.1, reasoning: "obstructed" } }],
  observations: [{ ...obs, review_status: "approved" }], ...o });

describe("report publishing flow", () => {
  beforeEach(() => { apiMock.mockReset(); apiMock.mockResolvedValue({}); });
  it("blocks publishing until every work package has a decision", () => {
    render(<DraftEditor id="r1" r={draft()} reload={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Publish report" })).toBeDisabled();
    expect(screen.getByText(/Not assessable from the footage/)).toBeInTheDocument();
    expect(screen.getByText(/Unknown is not treated as 0%/)).toBeInTheDocument();
  });
  it("blocks publishing while observations are pending", async () => {
    render(<DraftEditor id="r1" r={draft({ observations: [obs] })} reload={vi.fn()} />);
    await userEvent.click(screen.getByLabelText("Accept AI value"));
    expect(screen.getByRole("button", { name: "Publish report" })).toBeDisabled();
  });
  it("saves decisions then publishes after explicit confirmation", async () => {
    render(<DraftEditor id="r1" r={draft()} reload={vi.fn()} />);
    await userEvent.click(screen.getByLabelText("Accept AI value"));
    const publish = screen.getByRole("button", { name: "Publish report" });
    expect(publish).toBeEnabled();
    await userEvent.click(publish);
    expect(apiMock).not.toHaveBeenCalled();  // confirmation required first
    const buttons = await screen.findAllByRole("button", { name: "Publish" });
    await userEvent.click(buttons.at(-1)!);
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/reports/r1/publish", { method: "POST" }));
    const patch = apiMock.mock.calls[0];
    expect(patch[0]).toBe("/reports/r1");
    expect(patch[1].json.packages).toEqual([
      { work_package_id: "w1", decision: "accept", approved_percentage: undefined },
      { work_package_id: "w2", decision: "retain", approved_percentage: undefined }]);
  });
});

describe("one-click review", () => {
  beforeEach(() => { apiMock.mockReset(); apiMock.mockResolvedValue({}); });
  it("accepts all AI suggestions without publishing", async () => {
    const reload = vi.fn();
    render(<DraftEditor id="r1" r={draft({ observations: [obs] })} reload={reload} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept all suggestions" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/reports/r1/accept-all", { method: "POST" }));
    expect(apiMock).not.toHaveBeenCalledWith("/reports/r1/publish", expect.anything());
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });
  it("accept-all-and-publish needs an explicit confirmation, then runs accept, summary, publish in order", async () => {
    render(<DraftEditor id="r1" r={draft({ observations: [obs] })} reload={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept all & publish" }));
    expect(apiMock).not.toHaveBeenCalled();
    await userEvent.click((await screen.findAllByRole("button", { name: "Accept all & publish" })).at(-1)!);
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls.map((c) => c[0])).toEqual(["/reports/r1/accept-all", "/reports/r1", "/reports/r1/publish"]);
  });
  it("hides the shortcut once everything is already decided", () => {
    const done = draft();
    done.work_packages[0] = { ...done.work_packages[0], decision: "accept", approved_percentage: 70 };
    render(<DraftEditor id="r1" r={done} reload={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Accept all suggestions" })).toBeNull();
  });
});

describe("check before accepting big drops", () => {
  beforeEach(() => { apiMock.mockReset(); apiMock.mockResolvedValue({}); });
  const dropped = () => {
    const d = draft({ observations: [obs] });
    d.work_packages[0] = { ...d.work_packages[0], previous_approved_percentage: 50, ai: { assessable: true, proposed_completion_percentage: 10, confidence: 0.9, reasoning: "x" } };
    return d;
  };
  it("asks before a bulk accept and can hold the flagged package back", async () => {
    render(<DraftEditor id="r1" r={dropped()} reload={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept all suggestions" }));
    expect(apiMock).not.toHaveBeenCalled();
    expect(await screen.findByText(/AI 10% vs approved 50%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept the rest, review these" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/reports/r1/accept-all", { method: "POST", json: { skip_drops: true } }));
    expect(apiMock).not.toHaveBeenCalledWith("/reports/r1/publish", expect.anything());
  });
  it("lets the admin accept anyway, knowingly", async () => {
    render(<DraftEditor id="r1" r={dropped()} reload={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept all suggestions" }));
    await userEvent.click(await screen.findByRole("button", { name: "Accept anyway" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/reports/r1/accept-all", { method: "POST", json: undefined }));
  });
  it("accept-all-and-publish also stops at the check, then still needs its own confirmation", async () => {
    render(<DraftEditor id="r1" r={dropped()} reload={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept all & publish" }));
    await userEvent.click(await screen.findByRole("button", { name: "Accept anyway" }));
    expect(apiMock).not.toHaveBeenCalled();  // nothing happens until the publish confirmation
    expect(await screen.findByText("Accept all AI suggestions and publish?")).toBeInTheDocument();
  });
  it("does not interrupt when nothing dropped", async () => {
    render(<DraftEditor id="r1" r={draft({ observations: [obs] })} reload={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Accept all suggestions" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/reports/r1/accept-all", { method: "POST", json: undefined }));
    expect(screen.queryByText(/Check this value first/)).toBeNull();
  });
});
