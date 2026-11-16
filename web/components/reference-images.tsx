"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Empty, ErrorState, Loading } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import type { ReferenceImage } from "@/lib/types";
import { MAX_REFERENCES, validateReferenceFile } from "@/lib/validation";

/** Renders/elevations of the FINISHED site. Admin-only context for the AI; never shown to clients. */
export function ReferenceImages({ projectId, packages }: { projectId: string; packages: { work_package_id: string; name: string }[] }) {
  const list = useAsync(() => api<{ items: ReferenceImage[] }>(`/projects/${projectId}/reference-images`), [projectId]);
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const [pkg, setPkg] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const count = list.data?.items.length ?? 0;

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return setError("Choose an image.");
    const bad = validateReferenceFile(file);
    if (bad) return setError(bad);
    setError(null); setBusy(true);
    try {
      const q = new URLSearchParams({ filename: file.name });
      if (caption.trim()) q.set("caption", caption.trim());
      if (pkg) q.set("work_package_id", pkg);
      await api(`/projects/${projectId}/reference-images?${q}`, { method: "POST", body: file, headers: { "Content-Type": file.type } });
      toast.success("Reference image added");
      setFile(null); setCaption(""); setPkg(""); list.reload();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  async function remove(id: string) {
    try { await api(`/reference-images/${id}`, { method: "DELETE" }); toast.success("Reference image removed"); list.reload(); }
    catch (err) { toast.error((err as Error).message); }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Upload renders, elevations or design visuals of the finished site. The AI compares what it sees with them to suggest completion
        percentages. They are context only: you still approve every value, and clients never see them.
      </p>
      {list.loading && !list.data && <Loading rows={1} />}
      {list.error && <ErrorState error={list.error} retry={list.reload} />}
      {list.data && count === 0 && <Empty title="No reference images" hint="Add at least one view of the finished site." />}
      <ul className="grid gap-3 sm:grid-cols-3">
        {list.data?.items.map((r) => (
          <li key={r.id} className="space-y-1 text-xs">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={r.url} alt={r.caption ?? r.original_filename} className="h-32 w-full rounded border object-cover" />
            <p className="font-medium">{r.caption ?? r.original_filename}</p>
            <p className="text-muted-foreground">{r.work_package_name ?? "Whole site"}</p>
            <Button size="sm" variant="ghost" onClick={() => remove(r.id)} aria-label={`Remove ${r.caption ?? r.original_filename}`}>Remove</Button>
          </li>))}
      </ul>
      {count < MAX_REFERENCES ? (
        <form onSubmit={add} className="grid gap-3 sm:grid-cols-2" noValidate>
          <div className="space-y-1.5"><Label htmlFor="ref-file">Image (JPEG or PNG, up to 10 MB)</Label>
            <Input id="ref-file" type="file" accept="image/jpeg,image/png" disabled={busy} onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null); }} /></div>
          <div className="space-y-1.5"><Label htmlFor="ref-cap">Caption (e.g. “South elevation”)</Label>
            <Input id="ref-cap" value={caption} maxLength={500} disabled={busy} onChange={(e) => setCaption(e.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="ref-pkg">Shows work package</Label>
            <select id="ref-pkg" value={pkg} disabled={busy} onChange={(e) => setPkg(e.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
              <option value="">Whole site</option>
              {packages.map((p) => <option key={p.work_package_id} value={p.work_package_id}>{p.name}</option>)}
            </select></div>
          {error && <p role="alert" className="text-sm text-red-700 sm:col-span-2">{error}</p>}
          <div className="sm:col-span-2"><Button type="submit" disabled={busy}>{busy ? "Uploading…" : "Add reference image"}</Button></div>
        </form>
      ) : <p className="text-sm text-muted-foreground">Limit of {MAX_REFERENCES} reference images reached. Remove one to add another.</p>}
    </div>
  );
}
