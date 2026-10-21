import type { Metadata } from "next";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { ArticleVerificationWorkspace } from "@/components/verification/article-verification-workspace";

export const metadata: Metadata = {
  title: "Article Verification Preview | Explainable Verifier",
  description: "Review separate Wikipedia and external evidence for factual article claims.",
};

export default function ArticlePage() {
  const enabled = process.env.ARTICLE_VERIFICATION_ENABLED === "true";
  return (
    <div className="min-h-screen bg-[#0a0f19] text-slate-100 lg:flex">
      <AppSidebar />
      <main className="min-w-0 flex-1" id="article-main">
        <header className="border-b border-white/10 px-6 py-6 md:px-10">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">Article Intelligence</p>
          <h1 className="mt-2 text-2xl font-semibold">Article verification preview</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Extract factual claim candidates from a pasted article and inspect evidence with clear limitations.
            This is not a publisher-certified fact check.
          </p>
        </header>
        <div className="mx-auto max-w-[1250px] px-6 py-8 md:px-10">
          <ArticleVerificationWorkspace enabled={enabled} />
        </div>
      </main>
    </div>
  );
}
