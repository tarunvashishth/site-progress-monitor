import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import type { VideoRow } from "@/lib/types";
import { fmtDate } from "@/lib/validation";

/** The one thing the admin should do next, derived from the project's videos. No manual status checking. */
export function NextStep({ videos, onRetry }: { videos: VideoRow[]; onRetry: (id: string) => void }) {
  const busy = videos.find((v) => v.status === "queued" || v.status === "processing" || v.status === "uploaded");
  const failed = videos.find((v) => v.status === "failed");
  const toReview = videos.find((v) => v.report_status === "draft");
  const unreported = videos.find((v) => v.status === "analyzed" && !v.report_id);
  let body: React.ReactNode;
  if (busy) body = <p aria-live="polite">Analysing the {fmtDate(busy.capture_date)} video… this page updates by itself. Nothing to do yet.</p>;
  else if (failed) body = (<><p>The {fmtDate(failed.capture_date)} video could not be processed{failed.processing_error ? `: ${failed.processing_error}` : "."}</p>
    <Button size="sm" onClick={() => onRetry(failed.id)}>Try again</Button></>);
  else if (toReview) body = (<><p>The {fmtDate(toReview.capture_date)} report is ready for your review.</p>
    <Link href={`/admin/reports/${toReview.report_id}`} className={buttonVariants({ size: "sm" })}>Review &amp; publish</Link></>);
  else if (unreported) body = (<><p>The {fmtDate(unreported.capture_date)} video is analysed.</p>
    <Link href={`/admin/videos/${unreported.id}`} className={buttonVariants({ size: "sm" })}>Open and review</Link></>);
  else if (videos.length === 0) body = <p>Upload the first drone video below. Everything else happens automatically.</p>;
  else body = <p>All caught up. Upload the next video whenever it is ready.</p>;
  return (
    <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900">
      <div className="space-y-0.5"><p className="text-xs font-semibold uppercase tracking-wide text-sky-700">Next step</p>{body}</div>
    </div>
  );
}
