import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import type { Me, Role } from "@/lib/types";

/** Resolve the caller's role from the API (which reads it from the database), never from the token. */
export async function requireRole(role: Role): Promise<Me> {
  const supabase = await createClient();
  const { data: u } = await supabase.auth.getUser();
  if (!u.user) redirect("/login");
  const { data: s } = await supabase.auth.getSession();
  let me: Me | null = null;
  try {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/me`, {
      headers: { Authorization: `Bearer ${s.session?.access_token}` }, cache: "no-store",
    });
    if (res.ok) me = await res.json();
  } catch { /* API down */ }
  if (!me) redirect("/login?error=api");
  if (me.role !== role) redirect(me.role === "admin" ? "/admin" : "/client");
  return me;
}
