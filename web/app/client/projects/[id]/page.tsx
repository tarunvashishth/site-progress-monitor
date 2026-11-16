"use client";
import Link from "next/link";
import { use } from "react";
import { HistoryChart } from "@/components/history-chart";
import { PackageProgressList } from "@/components/package-progress";
import { ProgressBar } from "@/components/progress-bar";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { fmtDate, fmtPct } from "@/lib/validation";
import type { Page, ProjectDetail, ReportRow } from "@/lib/types";

export default function ClientProject({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const p = useAsync(() => api<ProjectDetail>(`/projects/${id}`), [id]);
  const reports = useAsync(() => api<Page<ReportRow>>(`/projects/${id}/reports`), [id]);
  if (p.loading) return <Loading />;
  if (p.error) return <ErrorState error={p.error} retry={p.reload} />;
  const d = p.data!;
  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-semibold">{d.name}</h1><p className="text-sm text-muted-foreground">{d.location ?? ""}</p></div>
      <Card><CardHeader><CardTitle>Current progress</CardTitle></CardHeader><CardContent className="space-y-5">
        <ProgressBar value={d.overall_progress} size="lg" label="Overall approved progress" />
        {d.latest_report
          ? <p className="text-sm text-muted-foreground">Last assessed {fmtDate(d.latest_report.published_at)} · {fmtPct(d.latest_report.assessment_coverage_percentage)} of project weight assessed</p>
          : <p className="text-sm text-muted-foreground">No report has been published yet. Progress shown is the agreed starting point.</p>}
        <PackageProgressList items={d.work_packages} />
      </CardContent></Card>
      {d.latest_report && <Card><CardHeader><CardTitle>Latest update</CardTitle></CardHeader><CardContent className="space-y-2">
        <p>{d.latest_report.summary}</p><Link className="text-sm underline" href={`/client/reports/${d.latest_report.id}`}>View full report and video →</Link></CardContent></Card>}
      {d.history.length > 0 && <Card><CardHeader><CardTitle>Progress history</CardTitle></CardHeader><CardContent><HistoryChart data={d.history} /></CardContent></Card>}
      <Card><CardHeader><CardTitle>Published reports</CardTitle></CardHeader><CardContent>
        {reports.loading && <Loading rows={2} />}
        {reports.error && <ErrorState error={reports.error} retry={reports.reload} />}
        {reports.data?.items.length === 0 && <Empty title="No published reports yet" />}
        <ul className="divide-y">{reports.data?.items.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-3 text-sm">
            <span>{fmtDate(r.capture_date)} · {fmtPct(r.overall_progress_percentage)}</span>
            <Link className="underline" href={`/client/reports/${r.id}`}>View</Link></li>))}</ul>
      </CardContent></Card>
    </div>
  );
}
