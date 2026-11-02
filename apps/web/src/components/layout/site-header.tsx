import Link from "next/link";
import { Suspense } from "react";
import { AuthNavigation, GuestNavigation } from "@/components/auth/auth-navigation";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 flex h-16 items-center justify-between gap-3 border-b border-white/10 bg-[#0e1420]/95 px-4 text-slate-100 backdrop-blur md:px-6">
      <Link href="/" aria-label="Explainable Verifier home" className="flex min-w-0 items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-blue-500 text-sm font-bold text-white" aria-hidden="true">
          EV
        </span>
        <span className="hidden truncate text-sm font-semibold sm:inline">Explainable Verifier</span>
      </Link>
      <Suspense fallback={<GuestNavigation />}>
        <AuthNavigation />
      </Suspense>
    </header>
  );
}
