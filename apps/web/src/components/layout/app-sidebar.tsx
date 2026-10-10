import Link from "next/link";
import { LockKeyhole } from "lucide-react";

const navigation = [
  { label: "Overview", href: "/" },
  { label: "Verify a Claim", href: "/verify" },
  { label: "Verification Pipeline", href: "/#pipeline" },
  { label: "Platform Capabilities", href: "/#capabilities" },
  { label: "Development Status", href: "/#status" },
] as const;

export function AppSidebar() {
  return (
    <aside className="border-b border-white/10 bg-[#0e1420] lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-[264px] lg:shrink-0 lg:flex-col lg:border-b-0 lg:border-r">
      <Link
        href="/"
        className="flex items-center gap-3 px-6 py-7"
        aria-label="Explainable Verifier home"
      >
        <div className="flex size-11 items-center justify-center rounded-xl bg-blue-500 font-bold text-white">
          EV
        </div>
        <div>
          <p className="font-semibold tracking-tight text-slate-100">
            Explainable Verifier
          </p>
          <p className="text-xs text-slate-500">Evidence Intelligence</p>
        </div>
      </Link>

      <nav
        aria-label="Primary navigation"
        className="flex flex-wrap gap-1 px-4 pb-5 lg:flex-col"
      >
        {navigation.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-lg px-4 py-3 text-sm text-slate-400 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="mt-auto hidden border-t border-white/10 p-6 lg:block">
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <LockKeyhole size={16} className="text-blue-400" aria-hidden="true" />
            Local workspace
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            Frontend development environment. Public verification requires
            authentication and rate limiting before deployment.
          </p>
        </div>
      </div>
    </aside>
  );
}
