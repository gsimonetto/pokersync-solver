import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { accentStyles } from "../data/modules.js";
import { fadeUp } from "../lib/motion.js";

/** Card de módulo: dor → valor → micro-métrica → CTA individual. */
export default function ModuleCard({ module }) {
  const accent = accentStyles[module.accent];
  const Icon = module.icon;

  return (
    <motion.article
      variants={fadeUp}
      whileHover={{ y: -6 }}
      transition={{ type: "spring", stiffness: 300, damping: 24 }}
      className={`group relative flex h-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.025] p-6 backdrop-blur-md transition-all duration-500 ${accent.hoverBorder} ${accent.glow}`}
    >
      {/* Brilho radial que acompanha o hover */}
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full opacity-0 blur-3xl transition-opacity duration-500 group-hover:opacity-100 ${accent.ring}`}
      />

      <div className="relative flex items-start justify-between gap-4">
        <span
          className={`flex h-12 w-12 items-center justify-center rounded-xl border bg-gradient-to-br transition-transform duration-500 group-hover:scale-110 ${accent.iconWrap}`}
        >
          <Icon className="h-5 w-5" strokeWidth={1.8} />
        </span>
        <span
          className={`rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${accent.badge}`}
        >
          {module.badge}
        </span>
      </div>

      <h3 className="relative mt-5 text-lg font-bold leading-snug text-white">
        {module.title}
      </h3>

      <p className="relative mt-3 text-sm leading-relaxed text-slate-400">
        {module.value}
      </p>

      <p className="relative mt-3 border-l-2 border-white/10 pl-3 text-xs leading-relaxed text-slate-500 transition-colors duration-500 group-hover:border-white/20">
        <span className="font-semibold text-slate-400">Sem PokerSync:</span>{" "}
        {module.pain}
      </p>

      <div className="relative mt-auto pt-6">
        <div className="flex items-baseline gap-2">
          <span className={`tabular text-2xl font-extrabold ${accent.metric}`}>
            {module.metric}
          </span>
          <span className="text-xs text-slate-500">{module.metricLabel}</span>
        </div>

        <a
          href={module.href}
          className={`mt-4 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors ${accent.cta}`}
        >
          {module.cta}
          <ArrowRight
            className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1"
            strokeWidth={2.2}
          />
        </a>
      </div>
    </motion.article>
  );
}
