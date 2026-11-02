import Link from "next/link";
import { Suspense } from "react";
import { connection } from "next/server";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { auth } from "@/auth";
import { logInWithGoogle } from "@/app/auth-actions";
import { SITE_NAME } from "@/lib/site-identity";

async function AuthPanel() {
  await connection();
  const session = await auth();

  if (session?.user?.id) {
    return (
      <div className="mt-8 space-y-5">
        <p className="text-sm text-slate-300">You are already logged in.</p>
        <Link href="/verify" className="flex items-center justify-center gap-2 rounded-xl bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-400">
          Verify a claim <ArrowRight size={17} aria-hidden="true" />
        </Link>
        <Link href="/account" className="block text-center text-sm text-blue-300 hover:text-blue-200">
          Go to my account
        </Link>
      </div>
    );
  }

  return (
    <div className="mt-8">
      <form action={logInWithGoogle}>
        <button type="submit" className="flex w-full items-center justify-center rounded-xl bg-white px-5 py-3 text-sm font-semibold text-slate-900 transition hover:bg-slate-200">
          Continue with Google
        </button>
      </form>
      <p className="mt-4 text-center text-xs leading-5 text-slate-400">
        Use your Google account to access claim and article verification.
      </p>
    </div>
  );
}

export function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const signup = mode === "signup";

  return (
    <main className="flex min-h-[calc(100dvh-4rem)] items-center justify-center bg-[#0a0f19] px-5 py-12 text-slate-100">
      <section aria-labelledby="auth-title" className="w-full max-w-md rounded-3xl border border-white/10 bg-[#101827] p-7 shadow-2xl shadow-black/20 sm:p-10">
        <span className="mb-6 inline-flex size-12 items-center justify-center rounded-2xl bg-blue-400/10 text-blue-300">
          <ShieldCheck size={25} aria-hidden="true" />
        </span>
        <p className="text-xs font-semibold leading-5 text-blue-300">{SITE_NAME}</p>
        <h1 id="auth-title" className="mt-3 text-3xl font-semibold tracking-tight text-white">
          {signup ? "Create your account" : "Welcome back"}
        </h1>
        <p className="mt-3 text-sm leading-6 text-slate-400">
          {signup
            ? "Get started with your Google account to verify claims and explore the evidence."
            : "Log in with your Google account to continue verifying claims and articles."}
        </p>
        <Suspense fallback={<p role="status" className="mt-8 text-sm text-slate-400">Checking your account…</p>}>
          <AuthPanel />
        </Suspense>
        <p className="mt-8 border-t border-white/10 pt-6 text-center text-sm text-slate-400">
          {signup ? "Already have an account? " : "New here? "}
          <Link href={signup ? "/login" : "/signup"} className="font-medium text-blue-300 hover:text-blue-200">
            {signup ? "Log in" : "Sign up"}
          </Link>
        </p>
      </section>
    </main>
  );
}
