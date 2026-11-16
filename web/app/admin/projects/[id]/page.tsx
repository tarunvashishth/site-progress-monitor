"use client";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { toast } from "sonner";
import { PackageEditor, packageErrors, type PackageRow } from "@/components/package-editor";
import { NextStep } from "@/components/next-step";
import { PackageProgressList } from "@/components/package-progress";
import { ReferenceImages } from "@/components/reference-images";
import { ProgressBar } from "@/components/progress-bar";
import { Empty, ErrorState, Loading } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { VideoUpload } from "@/components/video-upload";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { fmtDate, fmtPct } from "@/lib/validation";
import type { Page, ProjectDetail, ReportRow, VideoRow } from "@/lib/types";

export default function AdminProject({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const project = useAsync(() => api<ProjectDetail>(`/projects/${id}`), [id]);
  const videos = useAsync(() => api<Page<VideoRow>>(`/projects/${id}/videos`), [id]);
  const reports = useAsync(() => api<Page<ReportRow>>(`/projects/${id}/reports`), [id]);
  const members = useAsync(() => api<{ id: string; email: string }[]>(`/projects/${id}/members`), [id]);
  const [email, setEmail] = useState("");
  const [editing, setEditing] = useState<PackageRow[] | null>(null);
  const [pkgError, setPkgError] = useState<string | null>(null);

  const busy = videos.data?.items.some((v) => ["queued", "processing", "uploaded"].includes(v.status));
  const reloadVideos = videos.reload;
  useEffect(() => {  // follow processing automatically: no manual refreshing
    if (!busy) return;
    const t = setInterval(reloadVideos, 5000);
    return () => clearInterval(t);
  }, [busy, reloadVideos]);

  if (project.loading) return <Loading />;
  if (project.error) return <ErrorState error={project.error} retry={project.reload} />;
  const p = project.data!;

  async function assign(e: React.FormEvent) {
    e.preventDefault();
    try { await api(`/projects/${id}/members`, { method: "POST", json: { email } }); setEmail(""); toast.success("Client assigned"); members.reload(); }
    catch (err) { toast.error((err as Error).message); }
  }
  async function savePackages() {
    const err = editing && packageErrors(editing);
    if (err) return setPkgError(err);
    try {
      await api(`/projects/${id}/work-packages`, { method: "POST", json: { work_packages: editing!.map((r, i) => ({
        id: r.id, name: r.name.trim(), weight_percentage: Number(r.weight_percentage),
        initial_approved_percentage: Number(r.initial_approved_percentage), display_order: i })) } });
      toast.success("Work packages saved"); setEditing(null); setPkgError(null); project.reload();
    } catch (e) { setPkgError((e as Error).message); }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{p.name}</h1>
        <p className="text-sm text-muted-foreground">{p.location ?? "No location"} · started {fmtDate(p.start_date)} · <StatusBadge status={p.status} /></p>
        {p.description && <p className="mt-2 text-sm">{p.description}</p>}
      </div>
      {videos.data && <NextStep videos={videos.data.items} onRetry={async (vid) => {
        try { await api(`/videos/${vid}/retry`, { method: "POST" }); toast.success("Retry queued"); videos.reload(); } catch (e) { toast.error((e as Error).message); } }} />}

      <Card><CardHeader><CardTitle>Approved progress</CardTitle></CardHeader><CardContent className="space-y-5">
        <ProgressBar value={p.overall_progress} size="lg" label="Overall (approved, published)" />
        {p.latest_report && <p className="text-sm text-muted-foreground">Latest assessment {fmtDate(p.latest_report.published_at)} · coverage {fmtPct(p.latest_report.assessment_coverage_percentage)}</p>}
        {editing ? (<div className="space-y-3">
          <PackageEditor rows={editing} onChange={setEditing} />
          {pkgError && <p role="alert" className="text-sm text-red-700">{pkgError}</p>}
          <div className="flex gap-2"><Button onClick={savePackages}>Save packages</Button><Button variant="outline" onClick={() => { setEditing(null); setPkgError(null); }}>Cancel</Button></div>
        </div>) : (<>
          <PackageProgressList items={p.work_packages} />
          <Button variant="outline" size="sm" onClick={() => setEditing(p.work_packages.map((w) => ({ id: w.work_package_id, name: w.name,
            weight_percentage: String(Number(w.weight_percentage)), initial_approved_percentage: String(w.approved_percentage) })))}>Edit work packages</Button>
        </>)}
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Finished-site reference images</CardTitle></CardHeader><CardContent>
        <ReferenceImages projectId={id} packages={p.work_packages} />
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Upload drone video</CardTitle></CardHeader><CardContent>
        <VideoUpload projectId={id} onDone={() => videos.reload()} />
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Videos &amp; processing</CardTitle></CardHeader><CardContent>
        {videos.loading && <Loading rows={2} />}
        {videos.error && <ErrorState error={videos.error} retry={videos.reload} />}
        {videos.data?.items.length === 0 && <Empty title="No videos uploaded" />}
        <ul className="divide-y">
          {videos.data?.items.map((v) => (
            <li key={v.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
              <div><p className="font-medium">{fmtDate(v.capture_date)} · {v.original_filename}</p>
                {v.processing_error && <p className="text-red-700">{v.processing_error}</p>}</div>
              <div className="flex items-center gap-2">
                <StatusBadge status={v.status} />{v.report_status && <StatusBadge status={v.report_status} />}
                {v.status === "failed" && <Button size="sm" variant="outline" onClick={async () => {
                  try { await api(`/videos/${v.id}/retry`, { method: "POST" }); toast.success("Retry queued"); videos.reload(); } catch (e) { toast.error((e as Error).message); } }}>Retry</Button>}
                <Link href={`/admin/videos/${v.id}`} className={buttonVariants({ size: "sm", variant: "secondary" })}>Review</Link>
              </div>
            </li>))}
        </ul>
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Reports</CardTitle></CardHeader><CardContent>
        {reports.data?.items.length === 0 && <Empty title="No reports yet" hint="Review an analysed video to create a draft report." />}
        <ul className="divide-y">
          {reports.data?.items.map((r) => (
            <li key={r.id} className="flex items-center justify-between py-3 text-sm">
              <span>{fmtDate(r.capture_date)} · {r.status === "published" ? fmtPct(r.overall_progress_percentage) : "not published"}</span>
              <span className="flex items-center gap-2"><StatusBadge status={r.status} /><Link className="underline" href={`/admin/reports/${r.id}`}>Open</Link></span>
            </li>))}
        </ul>
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Client access</CardTitle></CardHeader><CardContent className="space-y-3">
        <ul className="text-sm">{members.data?.map((m) => (
          <li key={m.id} className="flex items-center justify-between py-1">{m.email}
            <Button variant="ghost" size="sm" onClick={async () => { await api(`/projects/${id}/members/${m.id}`, { method: "DELETE" }); members.reload(); }}>Remove</Button></li>))}
          {members.data?.length === 0 && <li className="text-muted-foreground">No clients assigned.</li>}</ul>
        <form onSubmit={assign} className="flex items-end gap-2">
          <div className="flex-1 space-y-1.5"><Label htmlFor="em">Assign an existing client account by email</Label>
            <Input id="em" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
          <Button type="submit">Assign</Button>
        </form>
      </CardContent></Card>
    </div>
  );
}
