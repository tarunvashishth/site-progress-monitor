"use client";
import Link from "next/link";
import { Empty, ErrorState, Loading } from "@/components/states";
import { MetricCard } from "@/components/metric-card";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { fmtDate } from "@/lib/validation";
import type { Dashboard } from "@/lib/types";

export default function AdminDashboard() {
  const { data, error, loading, reload } = useAsync(() => api<Dashboard>("/dashboard"));
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      {loading && <Loading />}
      {error && <ErrorState error={error} retry={reload} />}
      {data && (<>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="Total projects" value={data.total_projects} />
          <MetricCard label="Active projects" value={data.active_projects} />
          <MetricCard label="Uploaded videos" value={data.total_videos} />
          <MetricCard label="Reports awaiting review" value={data.reports_awaiting_review} hint="Draft reports" />
        </div>
        <Card><CardHeader><CardTitle>Recent activity</CardTitle></CardHeader><CardContent>
          {data.recent_activity.length === 0 ? <Empty title="No activity yet" hint="Create a project and upload a drone video to get started." /> : (
            <ul className="divide-y">
              {data.recent_activity.map((a) => (
                <li key={`${a.kind}-${a.id}`} className="flex items-center justify-between py-2 text-sm">
                  <span>{a.kind === "report" ? "Report" : "Video"} · <b>{a.project}</b></span>
                  <span className="flex items-center gap-3"><StatusBadge status={a.detail} /><span className="text-muted-foreground">{fmtDate(a.at)}</span></span>
                </li>))}
            </ul>)}
        </CardContent></Card>
        <Link href="/admin/projects/new" className="inline-block text-sm underline">Create a project →</Link>
      </>)}
    </div>
  );
}
