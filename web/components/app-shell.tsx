"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import type { Me } from "@/lib/types";

export function navFor(role: Me["role"]) {
  return role === "admin"
    ? [{ href: "/admin", label: "Dashboard" }, { href: "/admin/projects", label: "Projects" }]
    : [{ href: "/client", label: "My projects" }];
}

export function AppShell({ me, children }: { me: Me; children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const nav = navFor(me.role);
  async function logout() {
    await createClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }
  return (
    <div className="min-h-screen bg-stone-50 md:flex">
      <aside className="border-b bg-stone-900 p-4 text-stone-100 md:min-h-screen md:w-56 md:border-b-0">
        <p className="mb-4 text-sm font-semibold tracking-wide text-amber-400">SITE PROGRESS</p>
        <nav aria-label="Main" className="flex gap-2 md:flex-col">
          {nav.map((n) => {
            const active = n.href === path || (n.href !== "/admin" && n.href !== "/client" && path.startsWith(n.href));
            return <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
              className={`rounded-md px-3 py-2 text-sm ${active ? "bg-amber-500 text-stone-900" : "hover:bg-stone-800"}`}>{n.label}</Link>;
          })}
        </nav>
      </aside>
      <div className="flex-1">
        <header className="flex items-center justify-end gap-3 border-b bg-white px-6 py-3">
          <div className="text-right text-sm">
            <p className="font-medium">{me.full_name || me.email}</p>
            <p className="text-xs capitalize text-muted-foreground">{me.role}</p>
          </div>
          <Button variant="outline" size="sm" onClick={logout}>Log out</Button>
        </header>
        <main className="mx-auto max-w-6xl p-6">{children}</main>
      </div>
    </div>
  );
}
