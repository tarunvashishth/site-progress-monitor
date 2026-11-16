"use client";
import Link from "next/link";
import { Empty, ErrorState, Loading } from "@/components/states";
import { ProjectCard } from "@/components/project-card";
import { buttonVariants } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import type { Page, ProjectSummary } from "@/lib/types";

export default function Projects() {
  const { data, error, loading, reload } = useAsync(() => api<Page<ProjectSummary>>("/projects"));
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <Link href="/admin/projects/new" className={buttonVariants()}>New project</Link>
      </div>
      {loading && <Loading />}
      {error && <ErrorState error={error} retry={reload} />}
      {data && data.items.length === 0 && <Empty title="No projects yet" hint="Create your first project and configure its work packages." />}
      {data && data.items.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((p) => <ProjectCard key={p.id} p={p} href={`/admin/projects/${p.id}`} />)}
        </div>)}
    </div>
  );
}
