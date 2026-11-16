"use client";
import { useRouter } from "next/navigation";
import { use, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ComparisonPanel, CompareControl } from "@/components/comparison-panel";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ObservationCard } from "@/components/observation-card";
import { ErrorState, Loading } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { fmtDate } from "@/lib/validation";
import type { AnalysisView, ProjectDetail } from "@/lib/types";

export default function VideoReview({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const view = useAsync(() => api<AnalysisView>(`/videos/${id}/analysis`), [id]);
  const playback = useAsync(() => api<{ url: string }>(`/videos/${id}/playback-url`), [id]);
  const projectId = view.data?.video.project_id;
  const project = useAsync(() => (projectId ? api<ProjectDetail>(`/projects/${projectId}`) : Promise.resolve(null)), [projectId]);
  const names = Object.fromEntries((project.data?.work_packages ?? []).map((w) => [w.work_package_id, w.name]));
  const video = useRef<HTMLVideoElement>(null);
  const [confirm, setConfirm] = useState(false);
  const status = view.data?.video.status;

  useEffect(() => {  // poll while the worker is busy
    if (status !== "queued" && status !== "processing") return;
    const t = setInterval(view.reload, 5000);
    return () => clearInterval(t);
  }, [status, view.reload]);

  if (view.loading && !view.data) return <Loading />;
  if (view.error) return <ErrorState error={view.error} retry={view.reload} />;
  const d = view.data!;
  const seek = (t: number) => { if (video.current) { video.current.currentTime = t; void video.current.play(); } };
  const pending = d.observations.filter((o) => (o.review_status ?? "pending") === "pending").length;
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); toast.success(ok); view.reload(); } catch (e) { toast.error((e as Error).message); } };

  async function createDraft() {
    try {
      const r = await api<{ id: string }>(`/projects/${d.video.project_id}/reports/draft`, { method: "POST", json: { video_id: id } });
      router.push(`/admin/reports/${r.id}`);
    } catch (e) {
      const err = e as { code?: string; details?: { report_id?: string }; message: string };
      if (err.code === "report_exists" && err.details?.report_id) router.push(`/admin/reports/${err.details.report_id}`);
      else toast.error(err.message);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">Video {fmtDate(d.video.capture_date)}</h1>
          <p className="text-sm text-muted-foreground">{d.video.original_filename}</p></div>
        <div className="flex items-center gap-2"><StatusBadge status={d.video.status} />{d.video.report_status && <StatusBadge status={d.video.report_status} />}</div>
      </div>

      {!d.ai_configured && (
        <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          The AI service is not configured (QWEN_VL_BASE_URL / QWEN_VL_MODEL). Frames are extracted and kept; no observations or progress
          estimates are generated until it is configured. After configuring, use Retry.
        </div>)}
      {d.video.processing_error && <ErrorState error={new Error(d.video.processing_error)} />}
      {(status === "queued" || status === "processing") && <p className="text-sm text-sky-700" aria-live="polite">Processing… this page refreshes automatically.</p>}

      <Card><CardContent className="pt-5">
        {playback.data ? <video ref={video} src={playback.data.url} controls preload="metadata" className="w-full rounded-lg bg-black" /> : <Loading rows={1} />}
      </CardContent></Card>

      <div className="flex flex-wrap gap-2">
        {status === "failed" && <Button onClick={() => act(() => api(`/videos/${id}/retry`, { method: "POST" }), "Retry queued")}>Retry processing</Button>}
        {(status === "analyzed") && !d.video.report_status && <Button onClick={createDraft}>Create draft report</Button>}
        {d.video.report_status && <Button variant="secondary" onClick={createDraft}>Open report</Button>}
        {(status === "analyzed" || status === "failed") && d.frames.length > 0 && d.video.report_status !== "published" && (
          <Button variant="outline" onClick={() => setConfirm(true)}>Re-run AI analysis</Button>)}
      </div>

      {(status === "analyzed" || status === "failed") && d.frames.length > 0 && d.video.report_status !== "published" && (
        <CompareControl projectId={d.video.project_id} videoId={id} captureDate={d.video.capture_date} onQueued={view.reload} />)}

      {d.analysis && (
        <Card><CardHeader><CardTitle>AI analysis <StatusBadge status={d.analysis.status} /></CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
          <p className="text-muted-foreground">Model {d.analysis.model_name} · prompt {d.analysis.prompt_version}. AI output is a suggestion; nothing is visible to clients until you approve and publish.</p>
          {d.analysis.structured_response?.summary && <p>{d.analysis.structured_response.summary}</p>}
          {d.analysis.error_message && <p className="text-red-700">{d.analysis.error_message}</p>}
          {!!d.analysis.structured_response?.validation_warnings?.length && (
            <details><summary className="cursor-pointer text-amber-800">{d.analysis.structured_response.validation_warnings.length} validation note(s)</summary>
              <ul className="list-disc pl-5">{d.analysis.structured_response.validation_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>)}
        </CardContent></Card>)}

      <ComparisonPanel view={d} names={names} />

      {d.observations.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Observations {pending > 0 && <span className="text-sm font-normal text-amber-700">· {pending} pending review</span>}</h2>
          {d.observations.map((o) => (
            <ObservationCard key={o.id} o={{ ...o, evidence: o.evidence_frames.map((e) => ({ ...e, thumb_url: d.frames.find((f) => f.id === e.frame_id)?.thumb_url })) }}
              onChanged={view.reload} onSeek={seek} locked={d.video.report_status === "published"} />))}
        </section>)}

      {d.frames.length > 0 && (
        <details><summary className="cursor-pointer text-sm font-medium">All extracted frames ({d.frames.length})</summary>
          <div className="mt-3 flex flex-wrap gap-2">
            {d.frames.map((f) => (
              <button key={f.id} type="button" onClick={() => seek(f.timestamp_seconds)} className="text-xs text-muted-foreground">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {f.thumb_url && <img src={f.thumb_url} alt={`Frame ${f.frame_index}`} className="h-16 w-28 rounded border object-cover" />}
                #{f.frame_index} · {Math.round(f.timestamp_seconds)}s
              </button>))}
          </div></details>)}

      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Re-run AI analysis?"
        description="A new analysis is generated from the stored frames. If a draft report already exists it keeps the analysis it was created from."
        confirmLabel="Re-run" onConfirm={() => act(() => api(`/videos/${id}/analyze`, { method: "POST", json: { force: true } }), "Analysis queued")} />
    </div>
  );
}
