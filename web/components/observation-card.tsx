"use client";
import { useState } from "react";
import { toast } from "sonner";
import { EvidenceThumbs } from "@/components/evidence-thumbs";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { api } from "@/lib/api";
import type { Observation } from "@/lib/types";

export function ObservationCard({ o, onChanged, onSeek, locked }: {
  o: Observation; onChanged: () => void; onSeek?: (t: number) => void; locked?: boolean;
}) {
  const [edit, setEdit] = useState(false);
  const [title, setTitle] = useState(o.title);
  const [text, setText] = useState(o.description);
  const [confirmReject, setConfirmReject] = useState(false);
  const status = o.review_status ?? "pending";
  const evidence = o.evidence_frames ?? o.evidence;

  async function patch(body: Record<string, unknown>, msg: string) {
    try { await api(`/observations/${o.id}`, { method: "PATCH", json: body }); toast.success(msg); setEdit(false); onChanged(); }
    catch (e) { toast.error((e as Error).message); }
  }

  return (
    <div className="space-y-2 rounded-lg border bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        {edit ? <Input aria-label="Title" value={title} onChange={(e) => setTitle(e.target.value)} className="max-w-md" /> : <p className="font-medium">{o.title}</p>}
        <StatusBadge status={status} />
        <Badge variant="outline">{o.category}</Badge>
        <Badge variant="outline">{o.observation_type.replace(/_/g, " ")}</Badge>
        {o.work_package_name && <Badge variant="secondary">{o.work_package_name}</Badge>}
        {o.confidence != null && <span className="text-xs text-muted-foreground">AI confidence {Math.round(o.confidence * 100)}%</span>}
        {o.edited_by && <span className="text-xs text-amber-700">edited</span>}
      </div>
      {edit ? <Textarea aria-label="Description" value={text} onChange={(e) => setText(e.target.value)} /> : <p className="text-sm">{o.description}</p>}
      <EvidenceThumbs evidence={evidence} onSeek={onSeek} />
      {!locked && (
        <div className="flex flex-wrap gap-2">
          {edit ? (<>
            <Button size="sm" disabled={!title.trim() || !text.trim()} onClick={() => patch({ title, description: text }, "Observation updated")}>Save text</Button>
            <Button size="sm" variant="outline" onClick={() => { setEdit(false); setTitle(o.title); setText(o.description); }}>Cancel</Button>
          </>) : (<>
            <Button size="sm" disabled={status === "approved"} onClick={() => patch({ review_status: "approved" }, "Observation approved")}>Approve</Button>
            <Button size="sm" variant="outline" disabled={status === "rejected"} onClick={() => setConfirmReject(true)}>Reject</Button>
            <Button size="sm" variant="ghost" onClick={() => setEdit(true)}>Edit text</Button>
          </>)}
        </div>)}
      <ConfirmDialog open={confirmReject} onOpenChange={setConfirmReject} title="Reject this observation?"
        description="Rejected observations are excluded from the published report. You can approve it again later while the report is a draft."
        confirmLabel="Reject" onConfirm={() => patch({ review_status: "rejected" }, "Observation rejected")} />
    </div>
  );
}
