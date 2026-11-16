"use client";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { fmtPct } from "@/lib/validation";

export interface DropRow { work_package_id: string; name: string; previous_approved_percentage: number; ai?: { proposed_completion_percentage: number | null } | null }

/** Shown before a bulk accept when the AI suggests a value far below what was approved before. */
export function DropCheckDialog({ open, onOpenChange, drops, onReviewFirst, onAcceptAnyway }: {
  open: boolean; onOpenChange: (o: boolean) => void; drops: DropRow[]; onReviewFirst: () => void; onAcceptAnyway: () => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Check {drops.length === 1 ? "this value" : "these values"} first</AlertDialogTitle>
          <AlertDialogDescription>
            The AI suggests a much lower value than you approved before. That is usually a mistake in the AI&apos;s reading of the footage, not real regression.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <ul className="space-y-1 text-sm">
          {drops.map((d) => (
            <li key={d.work_package_id}><b>{d.name}</b>: AI {fmtPct(d.ai?.proposed_completion_percentage)} vs approved {fmtPct(d.previous_approved_percentage)}</li>))}
        </ul>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="outline" onClick={onAcceptAnyway}>Accept anyway</AlertDialogAction>
          <AlertDialogAction onClick={onReviewFirst}>Accept the rest, review these</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
