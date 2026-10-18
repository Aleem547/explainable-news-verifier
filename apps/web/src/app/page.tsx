
import {
  ArrowRight,
  CheckCircle2,
  Globe2,
  Layers3,
  ShieldCheck,
} from "lucide-react";

import { InfoCard } from "@/components/dashboard/info-card";
import { AppSidebar } from "@/components/layout/app-sidebar";
import {
  capabilities,
  pipelineStages,
} from "@/lib/dashboard-data";

export default function Home() {
  return (
    <div className="min-h-screen bg-[#0a0f19] text-slate-100 lg:flex">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-black"
      >
        Skip to content
      </a>

      <AppSidebar />

      <main id="main-content" className="min-w-0 flex-1">
        <header
          id="overview"
          className="flex scroll-mt-8 flex-wrap items-center justify-between gap-4 border-b border-white/10 px-6 py-5 md:px-10"
        >
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
              AI Verification Platform
            </p>

            <h1 className="mt-1 text-lg font-semibold">
              Platform Overview
            </h1>
          </div>

          <span className="inline-flex items-center gap-2 rounded-full border border-blue-400/20 bg-blue-400/10 px-4 py-2 text-xs font-medium text-blue-300">
            <span className="size-2 rounded-full bg-blue-400" />
            Production
          </span>
        </header>

        <div className="mx-auto max-w-[1350px] space-y-9 px-6 py-8 md:px-10">
          <section className="overflow-hidden rounded-3xl border border-blue-300/10 bg-gradient-to-br from-[#172640] via-[#111d32] to-[#101625] p-7 md:p-12">
            <div className="max-w-3xl">
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-300/20 bg-blue-400/10 px-3 py-2 text-xs font-medium text-blue-300">
                <ShieldCheck size={15} aria-hidden="true" />
                Evidence-first AI verification
              </div>

              <h2 className="text-3xl font-semibold leading-tight tracking-tight text-white md:text-5xl">
                Verify claims with context.
                <span className="block text-blue-400">
                  Not just confidence.
                </span>
              </h2>

              <p className="mt-6 max-w-2xl text-sm leading-7 text-slate-300 md:text-base">
                An evidence intelligence platform built to retrieve,
                evaluate, and trace information while preserving
                uncertainty and making verification decisions auditable.
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                <a
                  href="#pipeline"
                  className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-400"
                >
                  Explore verification pipeline
                  <ArrowRight size={17} aria-hidden="true" />
                </a>

                <a
                  href="#status"
                  className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-5 py-3 text-sm font-semibold text-slate-200 transition-colors hover:bg-white/10"
                >
                  View deployment status
                </a>
              </div>
            </div>
          </section>

          <section id="pipeline" className="scroll-mt-8 space-y-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">
                Core Architecture
              </p>

              <h2 className="mt-2 text-2xl font-semibold">
                Verification pipeline
              </h2>

              <p className="mt-2 text-sm text-slate-400">
                Three interconnected layers of evidence reasoning.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {pipelineStages.map((stage) => (
                <InfoCard
                  key={stage.number}
                  number={stage.number}
                  title={stage.title}
                  description={stage.description}
                  icon={stage.icon}
                />
              ))}
            </div>
          </section>

          <section id="capabilities" className="scroll-mt-8 space-y-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">
                Infrastructure
              </p>

              <h2 className="mt-2 text-2xl font-semibold">
                Platform capabilities
              </h2>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {capabilities.map((capability) => (
                <InfoCard
                  key={capability.title}
                  title={capability.title}
                  description={capability.description}
                  icon={capability.icon}
                  layout="horizontal"
                />
              ))}
            </div>
          </section>

          <section
            id="status"
            className="scroll-mt-8 rounded-2xl border border-white/10 bg-[#111a29] p-6 md:p-8"
          >
            <div className="flex items-center gap-3">
              <Globe2
                className="text-blue-400"
                size={22}
                aria-hidden="true"
              />

              <h2 className="text-xl font-semibold">
                Deployment status
              </h2>
            </div>

            <div className="mt-6 grid gap-5 md:grid-cols-3">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium text-green-300">
                  <CheckCircle2 size={16} aria-hidden="true" />
                  Backend deployed
                </div>

                <p className="mt-2 text-sm leading-6 text-slate-400">
                  FEVER evidence retrieval and NLI-based claim
                  verification are operational on AWS.
                </p>
              </div>

              <div>
                <div className="flex items-center gap-2 text-sm font-medium text-green-300">
                  <Layers3 size={16} aria-hidden="true" />
                  Frontend deployed
                </div>

                <p className="mt-2 text-sm leading-6 text-slate-400">
                  Responsive Next.js dashboard and explainable
                  verification results are live on Vercel.
                </p>
              </div>

              <div>
                <div className="flex items-center gap-2 text-sm font-medium text-amber-300">
                  <ShieldCheck size={16} aria-hidden="true" />
                  Independent corroboration pending
                </div>

                <p className="mt-2 text-sm leading-6 text-slate-400">
                  Current verdicts use a Wikipedia-derived corpus.
                  Independent cross-source verification remains
                  a documented limitation.
                </p>
              </div>
            </div>
          </section>

          <footer className="border-t border-white/10 py-6 text-xs text-slate-500">
            Explainable News Verifier · Production Deployment ·
            Live evidence-backed claim verification available.
          </footer>
        </div>
      </main>
    </div>
  );
}
