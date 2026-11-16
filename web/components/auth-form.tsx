"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createClient } from "@/lib/supabase/client";

function Form({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(params.get("error") === "api" ? "The server is unavailable. Try again shortly." : null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email")).trim(), password = String(f.get("password"));
    if (!/^\S+@\S+$/.test(email)) return setError("Enter a valid email address.");
    if (password.length < 8) return setError("Password must be at least 8 characters.");
    setBusy(true); setError(null);
    const supabase = createClient();
    if (mode === "login") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) { setBusy(false); return setError("Incorrect email or password."); }
      router.replace("/"); router.refresh();
    } else {
      const { data, error } = await supabase.auth.signUp({ email, password, options: { data: { full_name: String(f.get("name") ?? "") } } });
      setBusy(false);
      if (error) return setError(error.message);
      if (data.session) { router.replace("/"); router.refresh(); }
      else toast.success("Check your email to confirm your account, then log in.");
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-stone-100 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{mode === "login" ? "Log in" : "Create account"}</CardTitle>
          <CardDescription>{mode === "login" ? "Site Progress Monitor" : "New accounts are client accounts. Administrators are set up by your company."}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4" noValidate>
            {mode === "register" && (<div className="space-y-1.5"><Label htmlFor="name">Full name</Label><Input id="name" name="name" autoComplete="name" /></div>)}
            <div className="space-y-1.5"><Label htmlFor="email">Email</Label><Input id="email" name="email" type="email" autoComplete="email" required /></div>
            <div className="space-y-1.5"><Label htmlFor="password">Password</Label><Input id="password" name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required /></div>
            {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Log in" : "Register"}</Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            {mode === "login" ? <>No account? <Link className="underline" href="/register">Register</Link></> : <>Have an account? <Link className="underline" href="/login">Log in</Link></>}
          </p>
        </CardContent>
      </Card>
    </main>
  );
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  return <Suspense><Form mode={mode} /></Suspense>;
}
