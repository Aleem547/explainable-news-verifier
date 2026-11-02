import Link from "next/link";
import { Suspense } from "react";
import { AuthNavigation, GuestNavigation } from "@/components/auth/auth-navigation";

const HEADER_NAME = "Explainable Fake News Detection";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-[#0e1420]/95 px-4 py-3 text-slate-100 backdrop-blur md:px-6 lg:h-16 lg:flex-nowrap lg:py-0">
      <Link href="/" aria-label={`${HEADER_NAME} home`} className="flex w-full min-w-0 items-start gap-3 lg:w-auto lg:flex-1 lg:items-center">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-blue-500 text-sm font-bold text-white" aria-hidden="true">
          EV
        </span>
        <span className="text-xs font-semibold leading-5 [overflow-wrap:anywhere] sm:text-sm">{HEADER_NAME}</span>
      </Link>
      <div className="ml-auto shrink-0">
        <Suspense fallback={<GuestNavigation />}>
          <AuthNavigation />
        </Suspense>
      </div>
    </header>
  );
}
