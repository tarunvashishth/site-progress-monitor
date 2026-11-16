import { AppShell } from "@/components/app-shell";
import { requireRole } from "@/lib/server-auth";

export default async function ClientLayout({ children }: { children: React.ReactNode }) {
  const me = await requireRole("client");
  return <AppShell me={me}>{children}</AppShell>;
}
