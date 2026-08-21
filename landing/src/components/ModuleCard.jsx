import { useCallback, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { fadeUp } from "../lib/motion.js";

/**
 * Card de módulo da landing. Reaproveita o ModuleCardShell do produto:
 * a cor vem da custom property `--acc` e os utilitários `.acc-*` fazem
 * borda, glow, ícone e barra reagirem juntos. `is-active` replica o hover
 * no toque, onde :hover não existe.
 */
export default function ModuleCard({ module }) {
  const [active, setActive] = useState(false);
  const Icon = module.icon;

  const onPointerDown = useCallback((event) => {
    if (event.pointerType !== "mouse") setActive(true);
  }, []);

  const endTouch = useCallback((event) => {
    if (event.pointerType !== "mouse") {
      window.setTimeout(() => setActive(false), 180);
    }
  }, []);

  return (
    <motion.article
      variants={fadeUp}
      style={{ "--acc": module.accent }}
      onPointerDown={onPointerDown}
      onPointerUp={endTouch}
      onPointerCancel={endTouch}
      className={`group acc-card acc-lift relative flex h-full cursor-pointer flex-col overflow-hidden rounded-xl border border-hairline bg-surface p-5 ${
        active ? "is-active" : ""
      }`}
    >
      {/* Blob de brilho ambiente atrás do ícone. */}
      <div
        aria-hidden="true"
        className="acc-glow pointer-events-none absolute -left-10 -top-10 size-32 rounded-full blur-2xl"
      />

      <div className="relative flex items-start justify-between gap-2">
        <div className="acc-border flex size-10 items-center justify-center rounded-lg border border-hairline bg-elevated">
          <Icon size={20} className="acc-fg text-muted" />
        </div>
        <span className="acc-fg acc-border rounded-full border border-hairline px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted/70">
          {module.subtitle}
        </span>
      </div>

      <div className="relative mt-4">
        <h3 className="acc-fg text-base font-semibold text-ink">{module.title}</h3>
        <p className="mt-2 text-sm leading-relaxed text-muted">{module.value}</p>
        <p className="mt-3 border-l border-hairline pl-3 text-xs leading-relaxed text-muted/60">
          <span className="font-semibold text-muted">Sem PokerSync:</span> {module.pain}
        </p>
      </div>

      <div className="relative mt-auto pt-5">
        {/* Barra que acende na cor do módulo — mesmo padrão .acc-bar do produto. */}
        <div className="acc-bar mb-4 h-px w-full bg-hairline" />
        <div className="flex items-end justify-between gap-3">
          <div>
            <span className="tnum acc-fg block text-xl font-bold text-ink">
              {module.metric}
            </span>
            <span className="text-[11px] text-muted/60">{module.metricLabel}</span>
          </div>
          <a
            href={module.href}
            className="acc-fg inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-muted transition-colors"
          >
            {module.cta}
            <ArrowRight
              size={13}
              className="transition-transform duration-200 group-hover:translate-x-0.5"
            />
          </a>
        </div>
      </div>
    </motion.article>
  );
}
