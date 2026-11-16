import { fmtPct } from "@/lib/validation";

export function ProgressBar({ value, label, size = "md" }: { value: number; label?: string; size?: "sm" | "md" | "lg" }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const h = size === "lg" ? "h-4" : size === "sm" ? "h-1.5" : "h-2.5";
  return (
    <div>
      {label && <div className="mb-1 flex justify-between text-sm"><span>{label}</span><span className="font-medium tabular-nums">{fmtPct(v)}</span></div>}
      <div className={`${h} w-full overflow-hidden rounded-full bg-stone-200`} role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100} aria-label={label ?? "Progress"}>
        <div className="h-full rounded-full bg-amber-500 transition-all" style={{ width: `${v}%` }} />
      </div>
    </div>
  );
}
