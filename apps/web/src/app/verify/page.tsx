import type { Metadata } from "next";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { VerificationWorkspace } from "@/components/verification/verification-workspace";

export const metadata: Metadata = {
  title: "Verify a Claim | Explainable Verifier",
  description: "Inspect evidence-based verification results and model uncertainty.",
};

export default function VerifyPage() {
  return (
    <div className="min-h-screen bg-[#0a0f19] text-slate-100 lg:flex">
      <a
        href="#verification-main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-black"
      >
        Skip to verification workspace
      </a>
      <AppSidebar />
      <main id="verification-main" className="min-w-0 flex-1">
        <header className="border-b border-white/10 px-6 py-6 md:px-10">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">
            Evidence Intelligence
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white md:text-3xl">
            Claim verification
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Submit a factual claim to the existing FEVER-based verification pipeline.
            Results show model evidence signals, not an independent fact check.
          </p>
        </header>
        <div className="mx-auto max-w-[1250px] px-6 py-8 md:px-10">
          <VerificationWorkspace />
        </div>
      </main>
    </div>
  );
}
