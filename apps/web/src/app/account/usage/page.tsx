
import { Suspense } from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { connection } from "next/server";

import { auth } from "@/auth";
import UsagePanel from "./UsagePanel";

async function AuthenticatedUsage() {
  // Wait for an actual request before reading the session.
  // Required for Next.js 16 with cacheComponents enabled.
  await connection();

  const session = await auth();

  if (!session?.user?.id) {
    redirect("/account");
  }

  return <UsagePanel />;
}

export default function UsagePage() {
  return (
    <main className="min-h-screen bg-[#080f1d] px-6 py-12 text-white">
      <div className="mx-auto max-w-3xl space-y-8">
        <div className="space-y-3">
          <Link
            className="text-sm text-blue-300 hover:underline"
            href="/account"
          >
            ← Back to account
          </Link>

          <h1 className="text-3xl font-semibold">
            Your verification activity
          </h1>

          <p className="text-sm text-slate-400">
            Private activity summary for your signed-in account.
          </p>
        </div>

        <Suspense
          fallback={
            <p className="text-sm text-slate-400">
              Checking your session...
            </p>
          }
        >
          <AuthenticatedUsage />
        </Suspense>
      </div>
    </main>
  );
}
