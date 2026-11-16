"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { AnalysisView, Page, VideoRow } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { fmtDate } from "@/lib/validation";

const CHANGED: Record<string, string> = { yes: "Change visible", no: "No visible change", unclear: "Unclear" };

/** What the AI saw change versus an earlier capture. Suggestions only: nothing here is approved or published. */
export function ComparisonPanel({ view, names }: { view: AnalysisView; names: Record<string, string> }) {
  const sr = view.analysis?.structured_response;
  const cw = sr?.compared_with;
  if (!cw) return null;
  const cur = (i: number) => view.frames.find((f) => f.frame_index === i)?.thumb_url;
  const prev = (id: string) => view.compared_frames?.find((f) => f.id === id)?.thumb_url;
  return (
    <section className="space-y-3" aria-label="Comparison with earlier capture">
      <h2 className="text-lg font-semibold">Compared with {fmtDate(cw.capture_date)}</h2>
      {cw.pairs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No frames show a comparable view of the earlier capture, so no change is claimed.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {cw.pairs.map((p) => (
            <figure key={p.previous_frame_id} className="space-y-1 rounded border p-2 text-xs">
              <div className="grid grid-cols-2 gap-2">
                {/* eslint-disable @next/next/no-img-element */}
                <div><p className="mb-1 text-muted-foreground">Earlier · {fmtDate(cw.capture_date)}</p>{prev(p.previous_frame_id) && <img src={prev(p.previous_frame_id)!} alt={`Earlier frame ${p.previous_frame_index}`} className="h-24 w-full rounded object-cover" />}</div>
                <div><p className="mb-1 text-muted-foreground">This video · #{p.current_frame_index}</p>{cur(p.current_frame_index) && <img src={cur(p.current_frame_index)!} alt={`Current frame ${p.current_frame_index}`} className="h-24 w-full rounded object-cover" />}</div>
                {/* eslint-enable @next/next/no-img-element */}
              </div>
            </figure>))}
        </div>)}
      {!!sr?.comparison?.length && (
        <ul className="space-y-2 text-sm">
          {sr.comparison.map((c) => (
            <li key={c.work_package_id} className="rounded border p-3">
              <p className="font-medium">{names[c.work_package_id] ?? "Work package"}: {c.comparable ? CHANGED[c.changed] : "Views not comparable"}</p>
              {c.description && <p className="text-muted-foreground">{c.description}</p>}
            </li>))}
        </ul>)}
    </section>
  );
}

/** Choose which earlier capture to compare against, then re-run the analysis. */
export function CompareControl({ projectId, videoId, captureDate, onQueued }: { projectId: string; videoId: string; captureDate: string; onQueued: () => void }) {
  const vids = useAsync(() => api<Page<VideoRow>>(`/projects/${projectId}/videos`), [projectId]);
  const [choice, setChoice] = useState("");
  const earlier = (vids.data?.items ?? []).filter((v) => v.id !== videoId && v.status === "analyzed" && v.capture_date < captureDate);
  if (earlier.length === 0) return null;
  async function run() {
    try {
      await api(`/videos/${videoId}/analyze`, { method: "POST", json: { force: true, ...(choice ? { compare_to_video_id: choice } : {}) } });
      toast.success("Comparison queued"); onQueued();
    } catch (e) { toast.error((e as Error).message); }
  }
  return (
    <div className="flex flex-wrap items-end gap-2 text-sm">
      <div className="space-y-1.5">
        <label htmlFor="cmp" className="block font-medium">Compare with an earlier day</label>
        <select id="cmp" value={choice} onChange={(e) => setChoice(e.target.value)} className="h-9 rounded-md border bg-background px-2">
          <option value="">Latest earlier capture (automatic)</option>
          {earlier.map((v) => <option key={v.id} value={v.id}>{fmtDate(v.capture_date)} · {v.original_filename}</option>)}
        </select>
      </div>
      <Button variant="outline" onClick={run}>Re-run comparison</Button>
    </div>
  );
}
