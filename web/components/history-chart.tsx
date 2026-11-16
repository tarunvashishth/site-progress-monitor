"use client";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDate } from "@/lib/validation";

export function HistoryChart({ data }: { data: { published_at: string; overall_progress_percentage: number }[] }) {
  const rows = data.map((d) => ({ date: fmtDate(d.published_at), progress: Number(d.overall_progress_percentage) }));
  return (
    <div className="h-64 w-full" role="img" aria-label="Historical progress chart">
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ left: -10, right: 10, top: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
          <XAxis dataKey="date" tick={{ fontSize: 12 }} />
          <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} />
          <Tooltip formatter={(v) => [`${v}%`, "Progress"]} />
          <Line type="monotone" dataKey="progress" stroke="#f59e0b" strokeWidth={3} dot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
