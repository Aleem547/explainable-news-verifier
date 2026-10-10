
import type { LucideIcon } from "lucide-react";

interface InfoCardProps {
  title: string;
  description: string;
  icon: LucideIcon;
  number?: string;
  layout?: "vertical" | "horizontal";
}

export function InfoCard({
  title,
  description,
  icon: Icon,
  number,
  layout = "vertical",
}: InfoCardProps) {
  if (layout === "horizontal") {
    return (
      <article className="flex items-start gap-4 rounded-2xl border border-white/10 bg-[#111a29] p-6">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-white/5 text-blue-400">
          <Icon size={20} aria-hidden="true" />
        </div>

        <div>
          <h3 className="font-semibold text-white">{title}</h3>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            {description}
          </p>
        </div>
      </article>
    );
  }

  return (
    <article className="rounded-2xl border border-white/10 bg-[#111a29] p-6">
      <div className="flex items-center justify-between">
        <div className="flex size-11 items-center justify-center rounded-xl bg-blue-500/10 text-blue-400">
          <Icon size={21} aria-hidden="true" />
        </div>

        {number && (
          <span className="text-sm text-slate-500">{number}</span>
        )}
      </div>

      <h3 className="mt-6 font-semibold text-white">{title}</h3>

      <p className="mt-3 text-sm leading-6 text-slate-400">
        {description}
      </p>
    </article>
  );
}
