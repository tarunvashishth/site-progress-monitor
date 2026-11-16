"use client";
import { use } from "react";
import { ReportView } from "@/components/report-view";
import { ErrorState, Loading } from "@/components/states";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import type { Report } from "@/lib/types";

export default function ClientReport({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const r = useAsync(() => api<Report>(`/reports/${id}`), [id]);
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} retry={r.reload} />;
  return <div className="space-y-4"><h1 className="text-2xl font-semibold">Progress report</h1><ReportView report={r.data!} /></div>;
}
