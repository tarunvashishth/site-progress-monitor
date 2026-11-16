"use client";
import { useRef } from "react";
import { EvidenceThumbs } from "@/components/evidence-thumbs";
import { ProgressBar } from "@/components/progress-bar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtPct } from "@/lib/validation";
import type { Report } from "@/lib/types";

/** Published-report rendering shared by clients and admins. Shows approved data only. */
export function ReportView({ report }: { report: Report }) {
  const video = useRef<HTMLVideoElement>(null);
  const seek = (t: number) => { if (video.current) { video.current.currentTime = t; void video.current.play(); } };
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle>Overall progress · {fmtDate(report.capture_date)}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <ProgressBar value={report.overall_progress_percentage} size="lg" label="Approved overall progress" />
          <p className="text-sm text-muted-foreground">
            Assessment coverage {fmtPct(report.assessment_coverage_percentage)} of project weight.
            {report.retained_package_count > 0 && ` ${report.retained_package_count} work package(s) keep their earlier approved value.`}
          </p>
          <p className="whitespace-pre-wrap">{report.summary}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Work packages</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {report.work_packages.map((w) => (
            <div key={w.work_package_id}>
              <ProgressBar value={w.approved_percentage ?? 0} label={`${w.name} · weight ${w.weight_percentage}%`} />
              <p className="mt-1 text-xs text-muted-foreground">
                {w.assessed ? `Updated in this report (was ${fmtPct(w.previous_approved_percentage)})` : "Not re-assessed; earlier approved value retained"}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Site video</CardTitle></CardHeader>
        <CardContent>
          <video ref={video} src={report.video_url} controls preload="metadata" className="w-full rounded-lg bg-black" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Observations</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          {report.observations.length === 0 && <p className="text-sm text-muted-foreground">No observations were approved for this report.</p>}
          {report.observations.map((o) => (
            <div key={o.id} className="space-y-2 border-b pb-4 last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium">{o.title}</p>
                <Badge variant="outline">{o.category}</Badge>
                {o.work_package_name && <Badge variant="secondary">{o.work_package_name}</Badge>}
              </div>
              <p className="text-sm">{o.description}</p>
              <EvidenceThumbs evidence={o.evidence} onSeek={seek} />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
