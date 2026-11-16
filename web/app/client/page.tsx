"use client";
import { Empty, ErrorState, Loading } from "@/components/states";
import { ProjectCard } from "@/components/project-card";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import type { Page, ProjectSummary } from "@/lib/types";

export default function ClientHome() {
  const { data, error, loading, reload } = useAsync(() => api<Page<ProjectSummary>>("/projects"));
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">My projects</h1>
      {loading && <Loading />}
      {error && <ErrorState error={error} retry={reload} />}
      {data && data.items.length === 0 && <Empty title="No projects assigned" hint="Ask your contractor to assign you to a project." />}
      {data && data.items.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((p) => <ProjectCard key={p.id} p={p} href={`/client/projects/${p.id}`} />)}
        </div>)}
    </div>
  );
}
