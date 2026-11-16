"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/validation";
import type { Evidence } from "@/lib/types";

/** Thumbnails open a larger view; the large image URL is signed on demand (RLS-checked by the API). */
export function EvidenceThumbs({ evidence, onSeek }: { evidence: Evidence[]; onSeek?: (t: number) => void }) {
  const [big, setBig] = useState<{ url: string; t: number } | null>(null);
  async function open(e: Evidence) {
    try {
      const { url } = await api<{ url: string }>(`/frames/${e.frame_id}/image-url`);
      setBig({ url, t: e.timestamp_seconds });
    } catch (err) { toast.error((err as Error).message); }
  }
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {evidence.map((e) => (
          <div key={e.frame_id} className="w-28">
            <button type="button" onClick={() => open(e)} className="block overflow-hidden rounded-md border bg-stone-100 focus-visible:ring-2" aria-label={`Open frame at ${fmtTime(e.timestamp_seconds)}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {e.thumb_url ? <img src={e.thumb_url} alt={`Evidence at ${fmtTime(e.timestamp_seconds)}`} className="h-16 w-28 object-cover" /> : <div className="h-16 w-28" />}
            </button>
            <button type="button" className="mt-0.5 text-xs text-muted-foreground underline-offset-2 hover:underline" onClick={() => onSeek?.(e.timestamp_seconds)}>
              ▶ {fmtTime(e.timestamp_seconds)}
            </button>
          </div>
        ))}
      </div>
      <Dialog open={!!big} onOpenChange={(o) => !o && setBig(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader><DialogTitle>Evidence frame at {big ? fmtTime(big.t) : ""}</DialogTitle></DialogHeader>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {big && <img src={big.url} alt="Evidence frame" className="max-h-[70vh] w-full rounded object-contain" />}
        </DialogContent>
      </Dialog>
    </>
  );
}
