import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ComparisonPanel, CompareControl } from "@/components/comparison-panel";
import { ReferenceImages } from "@/components/reference-images";
import type { AnalysisView, ReferenceImage } from "@/lib/types";
import { validateReferenceFile } from "@/lib/validation";

const apiMock = vi.fn();
vi.mock("@/lib/api", () => ({ api: (...a: unknown[]) => apiMock(...a) }));

const pkgs = [{ work_package_id: "p1", name: "Foundation" }];
const img = (n: number): ReferenceImage => ({ id: `r${n}`, work_package_id: null, work_package_name: null, caption: `View ${n}`, original_filename: `v${n}.jpg`, url: `http://x/${n}.jpg`, created_at: "2026-01-01" });

describe("reference image validation", () => {
  it("accepts JPEG/PNG only, non-empty, up to 10 MB", () => {
    expect(validateReferenceFile({ size: 100, type: "image/png" })).toBeNull();
    expect(validateReferenceFile({ size: 100, type: "image/gif" })).toMatch(/JPEG or PNG/);
    expect(validateReferenceFile({ size: 0, type: "image/png" })).toMatch(/empty/);
    expect(validateReferenceFile({ size: 11 * 1024 * 1024, type: "image/jpeg" })).toMatch(/10 MB/);
  });
});

describe("ReferenceImages", () => {
  beforeEach(() => apiMock.mockReset());

  it("uploads the raw image with its content type, caption and package", async () => {
    apiMock.mockImplementation((path: string, init?: { method?: string }) =>
      Promise.resolve(init?.method === "POST" ? {} : { items: [] }));
    render(<ReferenceImages projectId="proj" packages={pkgs} />);
    await screen.findByText("No reference images");
    const file = new File(["x"], "south.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText(/Image \(JPEG or PNG/), file);
    await userEvent.type(screen.getByLabelText(/Caption/), "South elevation");
    await userEvent.selectOptions(screen.getByLabelText("Shows work package"), "p1");
    await userEvent.click(screen.getByRole("button", { name: "Add reference image" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith(
      "/projects/proj/reference-images?filename=south.png&caption=South+elevation&work_package_id=p1",
      { method: "POST", body: file, headers: { "Content-Type": "image/png" } }));
  });

  it("rejects a wrong file type without calling the API", async () => {
    apiMock.mockResolvedValue({ items: [] });
    render(<ReferenceImages projectId="proj" packages={pkgs} />);
    await screen.findByText("No reference images");
    // applyAccept:false so the browser-level accept filter does not hide the invalid file from the test
    await userEvent.setup({ applyAccept: false }).upload(screen.getByLabelText(/Image \(JPEG or PNG/), new File(["x"], "plan.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Add reference image" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("JPEG or PNG");
    expect(apiMock).toHaveBeenCalledTimes(1);  // only the initial list
  });

  it("stops offering uploads at the 6-image limit", async () => {
    apiMock.mockResolvedValue({ items: [1, 2, 3, 4, 5, 6].map(img) });
    render(<ReferenceImages projectId="proj" packages={pkgs} />);
    expect(await screen.findByText(/Limit of 6 reference images/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add reference image" })).toBeNull();
  });

  it("removes an image", async () => {
    apiMock.mockResolvedValue({ items: [img(1)] });
    render(<ReferenceImages projectId="proj" packages={pkgs} />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove View 1" }));
    expect(apiMock).toHaveBeenCalledWith("/reference-images/r1", { method: "DELETE" });
  });
});

const view = (over: Partial<NonNullable<AnalysisView["analysis"]>["structured_response"]> = {}): AnalysisView => ({
  video: { id: "v2", project_id: "proj", original_filename: "b.mp4", capture_date: "2026-06-08", description: null, status: "analyzed",
    processing_error: null, duration_seconds: 10, file_size: 1, job_status: null, job_type: null, attempts: null, job_error: null, report_id: null, report_status: null },
  job: null, ai_configured: true, observations: [],
  frames: [{ id: "c0", frame_index: 0, timestamp_seconds: 1, thumb_url: "http://x/cur0.jpg" }],
  compared_video: { id: "v1", capture_date: "2026-06-01", original_filename: "a.mp4" },
  compared_frames: [{ id: "e0", frame_index: 3, thumb_url: "http://x/old3.jpg" }],
  analysis: { id: "a", status: "completed", model_name: "m", prompt_version: "v2", error_message: null, structured_response: {
    compared_with: { video_id: "v1", capture_date: "2026-06-01", pairs: [{ current_frame_index: 0, previous_frame_id: "e0", previous_frame_index: 3, distance: 2 }] },
    comparison: [{ work_package_id: "p1", comparable: true, changed: "yes", description: "More formwork", evidence: [] },
                 { work_package_id: "p2", comparable: false, changed: "unclear", description: "", evidence: [] }], ...over } },
});

describe("ComparisonPanel", () => {
  it("shows paired earlier/current views and per-package findings", () => {
    render(<ComparisonPanel view={view()} names={{ p1: "Foundation", p2: "Roof" }} />);
    expect(screen.getByRole("img", { name: "Earlier frame 3" })).toHaveAttribute("src", "http://x/old3.jpg");
    expect(screen.getByRole("img", { name: "Current frame 0" })).toHaveAttribute("src", "http://x/cur0.jpg");
    expect(screen.getByText(/Foundation: Change visible/)).toBeInTheDocument();
    expect(screen.getByText("More formwork")).toBeInTheDocument();
    expect(screen.getByText(/Roof: Views not comparable/)).toBeInTheDocument();
  });
  it("says so when no views are comparable", () => {
    const v = view();
    v.analysis!.structured_response!.compared_with!.pairs = [];
    v.analysis!.structured_response!.comparison = [];
    render(<ComparisonPanel view={v} names={{}} />);
    expect(screen.getByText(/no change is claimed/)).toBeInTheDocument();
  });
  it("renders nothing without an earlier capture", () => {
    const { container } = render(<ComparisonPanel view={view({ compared_with: undefined })} names={{}} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("CompareControl", () => {
  beforeEach(() => apiMock.mockReset());
  const rows = [
    { id: "v1", original_filename: "a.mp4", capture_date: "2026-06-01", status: "analyzed" },
    { id: "v3", original_filename: "later.mp4", capture_date: "2026-07-01", status: "analyzed" },
    { id: "v0", original_filename: "bad.mp4", capture_date: "2026-05-01", status: "failed" },
  ];
  it("offers only earlier analyzed videos and sends the chosen one", async () => {
    apiMock.mockImplementation((...a: unknown[]) => { return Promise.resolve(String(a[0]).endsWith("/videos") ? { items: rows } : {}); });
    const queued = vi.fn();
    render(<CompareControl projectId="proj" videoId="v2" captureDate="2026-06-08" onQueued={queued} />);
    const sel = await screen.findByLabelText("Compare with an earlier day");
    expect(screen.getAllByRole("option")).toHaveLength(2);  // automatic + a.mp4 (not later, not failed)
    await userEvent.selectOptions(sel, "v1");
    await userEvent.click(screen.getByRole("button", { name: "Re-run comparison" }));
    expect(apiMock).toHaveBeenCalledWith("/videos/v2/analyze", { method: "POST", json: { force: true, compare_to_video_id: "v1" } });
    await waitFor(() => expect(queued).toHaveBeenCalled());
  });
  it("is hidden when there is no earlier analyzed video", async () => {
    apiMock.mockResolvedValue({ items: [rows[1]] });
    const { container } = render(<CompareControl projectId="proj" videoId="v2" captureDate="2026-06-08" onQueued={vi.fn()} />);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

import { ChangeVsEarlier } from "@/components/change-vs-earlier";
describe("ChangeVsEarlier", () => {
  it("shows the difference to the earlier approved value", () => {
    render(<ChangeVsEarlier proposed={60} earlier={50} />);
    expect(screen.getByText(/\+10 points vs earlier approved 50%/)).toBeInTheDocument();
  });
  it("warns when the suggestion is clearly lower than approved before", () => {
    render(<ChangeVsEarlier proposed={30} earlier={50} />);
    expect(screen.getByText(/-20 points.*check the evidence/)).toBeInTheDocument();
  });
  it("renders nothing for an unassessable package", () => {
    const { container } = render(<ChangeVsEarlier proposed={null} earlier={50} />);
    expect(container).toBeEmptyDOMElement();
  });
});

import { NextStep } from "@/components/next-step";
import type { VideoRow } from "@/lib/types";
const row = (o: Partial<VideoRow>): VideoRow => ({ id: "v", original_filename: "a.mp4", capture_date: "2026-06-01", description: null, status: "analyzed",
  processing_error: null, duration_seconds: 1, file_size: 1, job_status: null, job_type: null, attempts: null, job_error: null, report_id: null, report_status: null, ...o });
describe("NextStep", () => {
  it("asks for the first upload when there are no videos", () => {
    render(<NextStep videos={[]} onRetry={vi.fn()} />);
    expect(screen.getByText(/Upload the first drone video/)).toBeInTheDocument();
  });
  it("says nothing is needed while processing", () => {
    render(<NextStep videos={[row({ status: "processing" })]} onRetry={vi.fn()} />);
    expect(screen.getByText(/updates by itself/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("offers a retry for a failed video", async () => {
    const retry = vi.fn();
    render(<NextStep videos={[row({ id: "bad", status: "failed", processing_error: "too long" })]} onRetry={retry} />);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledWith("bad");
  });
  it("links straight to the draft report that needs review", () => {
    render(<NextStep videos={[row({ report_id: "r9", report_status: "draft" })]} onRetry={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Review & publish" })).toHaveAttribute("href", "/admin/reports/r9");
  });
  it("says all caught up when everything is published", () => {
    render(<NextStep videos={[row({ report_id: "r1", report_status: "published" })]} onRetry={vi.fn()} />);
    expect(screen.getByText(/All caught up/)).toBeInTheDocument();
  });
});
