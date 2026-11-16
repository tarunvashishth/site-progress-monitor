import { fmtPct } from "@/lib/validation";

/** The AI estimates without seeing earlier approved values; this shows the admin how its suggestion compares. */
export function ChangeVsEarlier({ proposed, earlier }: { proposed: number | null; earlier: number }) {
  if (proposed == null) return null;
  const delta = Math.round((proposed - earlier) * 10) / 10;
  const sign = delta > 0 ? "+" : "";
  return (
    <span className={delta < -5 ? "font-medium text-amber-800" : "text-muted-foreground"}>
      ({sign}{delta} points vs earlier approved {fmtPct(earlier)}
      {delta < -5 ? " — lower than approved before, check the evidence before accepting" : ""})
    </span>
  );
}
