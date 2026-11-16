import Link from "next/link";
import { ProgressBar } from "@/components/progress-bar";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { fmtDate } from "@/lib/validation";
import type { ProjectSummary } from "@/lib/types";

export function ProjectCard({ p, href }: { p: ProjectSummary; href: string }) {
  return (
    <Link href={href} className="block focus-visible:outline-2">
      <Card className="h-full transition hover:shadow-md"><CardContent className="space-y-3 pt-5">
        <div className="flex items-start justify-between gap-2">
          <div><p className="font-semibold">{p.name}</p><p className="text-sm text-muted-foreground">{p.location ?? "No location"}</p></div>
          <StatusBadge status={p.status} />
        </div>
        <ProgressBar value={p.overall_progress} label="Approved progress" />
        <p className="text-xs text-muted-foreground">{p.latest_report ? `Latest report ${fmtDate(p.latest_report.published_at)}` : "No published report yet"}</p>
      </CardContent></Card>
    </Link>
  );
}
