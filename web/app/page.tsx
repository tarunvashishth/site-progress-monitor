import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function Home() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/login");
  const { data: s } = await supabase.auth.getSession();
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/me`, {
    headers: { Authorization: `Bearer ${s.session?.access_token}` }, cache: "no-store",
  }).catch(() => null);
  if (!res?.ok) redirect("/login?error=api");
  const me = await res.json();
  redirect(me.role === "admin" ? "/admin" : "/client");
}
