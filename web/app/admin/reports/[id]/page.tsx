"use client";
import { use, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DropCheckDialog } from "@/components/drop-check-dialog";
import { ObservationCard } from "@/components/observation-card";
import { ProgressBar } from "@/components/progress-bar";
import { ReportView } from "@/components/report-view";
import { ErrorState, Loading } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { ChangeVsEarlier } from "@/components/change-vs-earlier";
import { BASIS_LABEL, flaggedDrops, fmtPct } from "@/lib/validation";
import type { Report, ReportItem } from "@/lib/types";

type Choice = { decision: "pending" | "accept" | "edit" | "retain"; value: string };

export default function AdminReport({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const rep = useAsync(() => api<Report>(`/reports/${id}`), [id]);
  if (rep.loading && !rep.data) return <Loading />;
  if (rep.error) return <ErrorState error={rep.error} retry={rep.reload} />;
  const r = rep.data!;
  if (r.status === "published") return (
    <div className="space-y-4"><div className="flex items-center gap-2"><h1 className="text-2xl font-semibold">Published report</h1><StatusBadge status="published" /></div>
      <p className="text-sm text-muted-foreground">Published reports are immutable snapshots.</p><ReportView report={r} /></div>);

  // remount when decisions change on the server (e.g. after "Accept all") so the form shows them
  return <DraftEditor key={`${id}:${r.work_packages.map((w) => w.decision).join(",")}`} id={id} r={r} reload={rep.reload} />;
}

export function DraftEditor({ id, r, reload }: { id: string; r: Report; reload: () => void }) {
  const [summary, setSummary] = useState(r.summary);
  const [choices, setChoices] = useState<Record<string, Choice>>(() => Object.fromEntries(r.work_packages.map((w) => [
    w.work_package_id, { decision: w.decision ?? "pending", value: String(w.approved_percentage ?? "") }])));
  const [confirm, setConfirm] = useState(false);
  const [quickConfirm, setQuickConfirm] = useState(false);
  const [dropCheck, setDropCheck] = useState<"accept" | "publish" | null>(null);
  const drops = flaggedDrops(r.work_packages);
  const acceptAll = (skipDrops: boolean) => run(() => api(`/reports/${id}/accept-all`, { method: "POST", json: skipDrops ? { skip_drops: true } : undefined }),
    skipDrops ? "Accepted the rest. Please decide the flagged value(s) yourself." : "AI suggestions accepted");
  const [busy, setBusy] = useState(false);
  const items = r.work_packages;
  const payload = () => items.flatMap((w) => {
    const c = choices[w.work_package_id];
    if (!c || c.decision === "pending") return [];
    return [{ work_package_id: w.work_package_id, decision: c.decision, approved_percentage: c.decision === "edit" ? Number(c.value) : undefined }];
  });
  const valid = items.every((w) => { const c = choices[w.work_package_id]; return c && c.decision !== "pending" && (c.decision !== "edit" || (c.value !== "" && Number(c.value) >= 0 && Number(c.value) <= 100)); });
  const pendingObs = r.observations.filter((o) => (o.review_status ?? "pending") === "pending").length;
  const save = () => api(`/reports/${id}`, { method: "PATCH", json: { summary, packages: payload() } });

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try { await fn(); toast.success(ok); reload(); } catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  }
  const setChoice = (wid: string, c: Partial<Choice>) => setChoices((s) => ({ ...s, [wid]: { ...s[wid], ...c } }));

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2"><h1 className="text-2xl font-semibold">Draft report</h1><StatusBadge status="draft" /></div>
      <Card><CardContent className="space-y-2 pt-5">
        <ProgressBar value={r.overall_progress_percentage} size="lg" label="Overall progress (preview, computed from approved values)" />
        <p className="text-sm text-muted-foreground">Coverage {fmtPct(r.assessment_coverage_percentage)} · packages not yet decided count as their earlier approved value in this preview.</p>
      </CardContent></Card>

      {(pendingObs > 0 || items.some((w) => (choices[w.work_package_id]?.decision ?? "pending") === "pending")) && (
        <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-5">
          <p className="max-w-xl text-sm">The AI has prepared everything. If the suggestions look right, accept them all in one click; you can still change any item below before publishing.</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy} onClick={() => (drops.length ? setDropCheck("accept") : void acceptAll(false))}>Accept all suggestions</Button>
            <Button disabled={busy || !summary.trim()} onClick={() => (drops.length ? setDropCheck("publish") : setQuickConfirm(true))}>Accept all &amp; publish</Button>
          </div>
        </CardContent></Card>)}

      <Card><CardHeader><CardTitle>Work package progress</CardTitle></CardHeader><CardContent className="space-y-5">
        {items.map((w: ReportItem) => {
          const c = choices[w.work_package_id] ?? { decision: "pending", value: "" };
          const ai = w.ai;
          return (
            <fieldset key={w.work_package_id} className="space-y-2 border-b pb-4 last:border-0">
              <legend className="font-medium">{w.name} <span className="text-sm font-normal text-muted-foreground">weight {w.weight_percentage}% · earlier approved {fmtPct(w.previous_approved_percentage)}</span></legend>
              {ai && ai.assessable
                ? <p className="text-sm">AI suggests <b>{fmtPct(ai.proposed_completion_percentage)}</b> (confidence {Math.round(ai.confidence * 100)}%{ai.basis ? ` · based on ${BASIS_LABEL[ai.basis] ?? ai.basis}` : ""}): {ai.reasoning}
                  {" "}<ChangeVsEarlier proposed={ai.proposed_completion_percentage} earlier={w.previous_approved_percentage} /></p>
                : <p className="text-sm text-muted-foreground">Not assessable from the footage{ai?.reasoning ? `: ${ai.reasoning}` : ""}. Unknown is not treated as 0%.</p>}
              <div className="flex flex-wrap items-center gap-4 text-sm">
                {ai?.assessable && <label className="flex items-center gap-1.5"><input type="radio" name={w.work_package_id} checked={c.decision === "accept"} onChange={() => setChoice(w.work_package_id, { decision: "accept" })} />Accept AI value</label>}
                <label className="flex items-center gap-1.5"><input type="radio" name={w.work_package_id} checked={c.decision === "edit"} onChange={() => setChoice(w.work_package_id, { decision: "edit" })} />Set value</label>
                {c.decision === "edit" && <Input aria-label={`${w.name} approved percentage`} className="w-24" inputMode="decimal" value={c.value} onChange={(e) => setChoice(w.work_package_id, { value: e.target.value })} />}
                <label className="flex items-center gap-1.5"><input type="radio" name={w.work_package_id} checked={c.decision === "retain"} onChange={() => setChoice(w.work_package_id, { decision: "retain" })} />Keep earlier value</label>
              </div>
            </fieldset>);
        })}
      </CardContent></Card>

      <Card><CardHeader><CardTitle>Summary (shown to the client)</CardTitle></CardHeader><CardContent>
        <Textarea aria-label="Report summary" rows={5} value={summary} onChange={(e) => setSummary(e.target.value)} />
      </CardContent></Card>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Observations {pendingObs > 0 && <span className="text-sm font-normal text-amber-700">· {pendingObs} pending review</span>}</h2>
        <p className="text-sm text-muted-foreground">Only approved observations are published.</p>
        {r.observations.map((o) => <ObservationCard key={o.id} o={o} onChanged={reload} />)}
        {r.observations.length === 0 && <p className="text-sm text-muted-foreground">The AI produced no observations.</p>}
      </section>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy} onClick={() => run(save, "Draft saved")}>Save draft</Button>
        <Button disabled={busy || !valid || pendingObs > 0 || !summary.trim()} onClick={() => setConfirm(true)}>Publish report</Button>
      </div>
      {(!valid || pendingObs > 0) && <p className="text-sm text-muted-foreground">To publish: decide every work package, review every observation, and add a summary.</p>}

      <DropCheckDialog open={dropCheck !== null} onOpenChange={(o) => !o && setDropCheck(null)} drops={drops}
        onReviewFirst={() => { setDropCheck(null); void acceptAll(true); }}
        onAcceptAnyway={() => { const next = dropCheck; setDropCheck(null); if (next === "publish") setQuickConfirm(true); else void acceptAll(false); }} />

      <ConfirmDialog open={quickConfirm} onOpenChange={setQuickConfirm} title="Accept all AI suggestions and publish?"
        description="Every pending observation and package value suggested by the AI will be approved as shown, and the report will be published to the assigned clients. Published reports cannot be edited."
        confirmLabel="Accept all & publish" onConfirm={() => run(async () => {
          await api(`/reports/${id}/accept-all`, { method: "POST" });
          await api(`/reports/${id}`, { method: "PATCH", json: { summary } });
          await api(`/reports/${id}/publish`, { method: "POST" });
        }, "Report published")} />

      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Publish this report?"
        description="Clients assigned to this project will see the approved progress, observations and video. Published reports cannot be edited."
        confirmLabel="Publish" onConfirm={() => run(async () => { await save(); await api(`/reports/${id}/publish`, { method: "POST" }); }, "Report published")} />
    </div>
  );
}
