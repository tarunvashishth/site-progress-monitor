import { Badge } from "@/components/ui/badge";

const tone: Record<string, string> = {
  published: "bg-emerald-100 text-emerald-800", analyzed: "bg-emerald-100 text-emerald-800", succeeded: "bg-emerald-100 text-emerald-800",
  approved: "bg-emerald-100 text-emerald-800", completed: "bg-emerald-100 text-emerald-800",
  draft: "bg-amber-100 text-amber-800", pending: "bg-amber-100 text-amber-800",
  queued: "bg-sky-100 text-sky-800", processing: "bg-sky-100 text-sky-800", running: "bg-sky-100 text-sky-800", uploaded: "bg-sky-100 text-sky-800",
  failed: "bg-red-100 text-red-800", rejected: "bg-red-100 text-red-800", unavailable: "bg-red-100 text-red-800",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant="secondary" className={tone[status] ?? ""}>{status.replace(/_/g, " ")}</Badge>;
}
