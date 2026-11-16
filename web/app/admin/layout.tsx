import { AppShell } from "@/components/app-shell";
import { requireRole } from "@/lib/server-auth";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const me = await requireRole("admin");
  return <AppShell me={me}>{children}</AppShell>;
}
