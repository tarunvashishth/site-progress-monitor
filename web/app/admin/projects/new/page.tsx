"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { PackageEditor, packageErrors, type PackageRow } from "@/components/package-editor";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { ProjectDetail } from "@/lib/types";

export default function NewProject() {
  const router = useRouter();
  const [f, setF] = useState({ name: "", location: "", description: "", start_date: "" });
  const [rows, setRows] = useState<PackageRow[]>([
    { name: "Foundation", weight_percentage: "20", initial_approved_percentage: "0" },
    { name: "Structure", weight_percentage: "40", initial_approved_percentage: "0" },
    { name: "Brickwork", weight_percentage: "20", initial_approved_percentage: "0" },
    { name: "Roofing", weight_percentage: "10", initial_approved_percentage: "0" },
    { name: "External work", weight_percentage: "10", initial_approved_percentage: "0" },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const err = !f.name.trim() ? "Project name is required." : packageErrors(rows);
    if (err) return setError(err);
    setBusy(true); setError(null);
    try {
      const p = await api<ProjectDetail>("/projects", { method: "POST", json: {
        name: f.name.trim(), location: f.location || null, description: f.description || null, start_date: f.start_date || null,
        work_packages: rows.map((r, i) => ({ name: r.name.trim(), weight_percentage: Number(r.weight_percentage),
          initial_approved_percentage: Number(r.initial_approved_percentage), display_order: i })) } });
      toast.success("Project created");
      router.push(`/admin/projects/${p.id}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="space-y-6" noValidate>
      <h1 className="text-2xl font-semibold">New project</h1>
      <Card><CardHeader><CardTitle>Project details</CardTitle></CardHeader><CardContent className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="name">Name *</Label><Input id="name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
        <div className="space-y-1.5"><Label htmlFor="loc">Location</Label><Input id="loc" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></div>
        <div className="space-y-1.5"><Label htmlFor="start">Start date</Label><Input id="start" type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></div>
        <div className="space-y-1.5 sm:col-span-2"><Label htmlFor="desc">Description</Label><Textarea id="desc" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Work packages</CardTitle></CardHeader><CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">Weights must total exactly 100%. &quot;Approved so far&quot; is the verified starting completion; unknown is never assumed to be 0 — enter the real baseline.</p>
        <PackageEditor rows={rows} onChange={setRows} />
      </CardContent></Card>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create project"}</Button>
    </form>
  );
}
