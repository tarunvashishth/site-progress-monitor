import { ProgressBar } from "@/components/progress-bar";
import type { PackageProgress } from "@/lib/types";

export function PackageProgressList({ items }: { items: PackageProgress[] }) {
  return (
    <ul className="space-y-4">
      {items.map((p) => (
        <li key={p.work_package_id}>
          <ProgressBar value={p.approved_percentage} label={`${p.name} · weight ${Number(p.weight_percentage)}%`} />
        </li>
      ))}
    </ul>
  );
}
