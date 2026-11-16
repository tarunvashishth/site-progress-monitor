"use client";
import { useState } from "react";
import { toast } from "sonner";
import { ProgressBar } from "@/components/progress-bar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { validateVideoFile, ALLOWED_EXT } from "@/lib/validation";

interface UploadTarget { video_id: string; upload_url: string }

/** Direct browser -> private Supabase Storage upload via a signed URL (the API never proxies video bytes). */
function putFile(url: string, file: File, onProgress: (pct: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("x-upsert", "false");
    const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (key) xhr.setRequestHeader("apikey", key);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("Network error during upload"));
    const body = new FormData();  // same body shape as supabase-js uploadToSignedUrl
    body.append("cacheControl", "3600");
    body.append("", file);
    xhr.send(body);
  });
}

export function VideoUpload({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [desc, setDesc] = useState("");
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return setError("Choose a video file.");
    const bad = validateVideoFile(file);
    if (bad) return setError(bad);
    if (!date) return setError("Select the capture date.");
    setError(null); setPct(0);
    try {
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      const t = await api<UploadTarget>(`/projects/${projectId}/videos/upload-url`, { method: "POST", json: {
        filename: file.name, content_type: ALLOWED_EXT[ext], file_size: file.size, capture_date: date, description: desc || null } });
      await putFile(t.upload_url, file, setPct);
      await api(`/videos/${t.video_id}/complete`, { method: "POST" });
      toast.success("Upload complete. Processing has been queued.");
      setFile(null); setDesc(""); setPct(null); onDone();
    } catch (err) { setError((err as Error).message); setPct(null); }
  }

  const uploading = pct !== null;
  return (
    <form onSubmit={start} className="space-y-3" noValidate>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="file">Drone video (MP4 or MOV)</Label>
          <Input id="file" type="file" accept=".mp4,.mov,video/mp4,video/quicktime" disabled={uploading} onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null); }} /></div>
        <div className="space-y-1.5"><Label htmlFor="cap">Capture date</Label><Input id="cap" type="date" value={date} disabled={uploading} onChange={(e) => setDate(e.target.value)} /></div>
        <div className="space-y-1.5 sm:col-span-2"><Label htmlFor="vd">Description (optional)</Label><Input id="vd" value={desc} disabled={uploading} onChange={(e) => setDesc(e.target.value)} /></div>
      </div>
      {uploading && <ProgressBar value={pct} label="Uploading" />}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <Button type="submit" disabled={uploading}>{uploading ? "Uploading…" : "Upload video"}</Button>
    </form>
  );
}
