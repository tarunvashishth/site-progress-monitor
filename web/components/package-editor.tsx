"use client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { weightsTotal } from "@/lib/validation";

export interface PackageRow { id?: string; name: string; weight_percentage: string; initial_approved_percentage: string; description?: string }

export function packageErrors(rows: PackageRow[]): string | null {
  if (rows.length === 0) return "Add at least one work package.";
  for (const r of rows) {
    if (!r.name.trim()) return "Every work package needs a name.";
    const w = Number(r.weight_percentage), p = Number(r.initial_approved_percentage);
    if (!(w > 0 && w <= 100)) return `${r.name}: weight must be between 0 and 100.`;
    if (r.initial_approved_percentage === "" || !(p >= 0 && p <= 100)) return `${r.name}: enter an approved starting completion (0–100).`;
  }
  if (new Set(rows.map((r) => r.name.trim().toLowerCase())).size !== rows.length) return "Work package names must be unique.";
  if (weightsTotal(rows) !== 100) return `Weights must total exactly 100% (currently ${weightsTotal(rows)}%).`;
  return null;
}

export function PackageEditor({ rows, onChange }: { rows: PackageRow[]; onChange: (r: PackageRow[]) => void }) {
  const set = (i: number, k: keyof PackageRow, v: string) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const total = weightsTotal(rows);
  return (
    <div className="space-y-3">
      <div className="hidden grid-cols-[1fr_7rem_9rem_auto] gap-2 text-xs text-muted-foreground sm:grid">
        <span>Name</span><span>Weight %</span><span>Approved so far %</span><span />
      </div>
      {rows.map((r, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-[1fr_7rem_9rem_auto]">
          <div><Label className="sm:sr-only" htmlFor={`n${i}`}>Name</Label><Input id={`n${i}`} value={r.name} onChange={(e) => set(i, "name", e.target.value)} placeholder="e.g. Foundation" /></div>
          <div><Label className="sm:sr-only" htmlFor={`w${i}`}>Weight %</Label><Input id={`w${i}`} inputMode="decimal" value={r.weight_percentage} onChange={(e) => set(i, "weight_percentage", e.target.value)} /></div>
          <div><Label className="sm:sr-only" htmlFor={`p${i}`}>Approved so far %</Label><Input id={`p${i}`} inputMode="decimal" value={r.initial_approved_percentage} onChange={(e) => set(i, "initial_approved_percentage", e.target.value)} /></div>
          <Button type="button" variant="ghost" onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label={`Remove ${r.name || "package"}`}>✕</Button>
        </div>
      ))}
      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" size="sm" onClick={() => onChange([...rows, { name: "", weight_percentage: "", initial_approved_percentage: "0" }])}>Add package</Button>
        <p className={`text-sm font-medium ${total === 100 ? "text-emerald-700" : "text-red-700"}`} aria-live="polite">Total weight: {total}%</p>
      </div>
    </div>
  );
}
