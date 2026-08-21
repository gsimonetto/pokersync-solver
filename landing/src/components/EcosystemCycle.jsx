import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BookOpen, Layers, Target, TrendingUp, ArrowRight, Repeat } from "lucide-react";
import SectionHeading from "./ui/SectionHeading.jsx";
import { ACCENT } from "../data/modules.js";
import { EASE, fadeUp, scaleIn, staggerContainer, viewportOnce } from "../lib/motion.js";

/** Cada etapa carrega o acento do módulo real correspondente. */
const steps = [
  {
    id: "revisor",
    label: "Revisão de Mãos",
    action: "Detecta o leak",
    icon: BookOpen,
    accent: ACCENT.purple,
    detail:
      "Importa a sessão, cruza cada decisão com a solução GTO e marca automaticamente os spots onde você deixou EV na mesa.",
    output: "3 leaks classificados por custo em bb/100",
  },
  {
    id: "ranges",
    label: "Construtor de Ranges",
    action: "Ajusta a estratégia",
    icon: Layers,
    accent: ACCENT.pink,
    detail:
      "O leak abre a matriz exata do spot. Você edita frequências combo a combo e salva a correção como range oficial.",
    output: "Range corrigida versionada na sua biblioteca",
  },
  {
    id: "treino",
    label: "Modo Treino",
    action: "Pratica o cenário",
    icon: Target,
    accent: ACCENT.green,
    detail:
      "A range corrigida vira um drill interativo com repetição espaçada, até a decisão certa virar reflexo na mesa.",
    output: "Drill gerado sem nenhuma exportação manual",
  },
  {
    id: "banca",
    label: "Banca & Evolution",
    action: "Acompanha o lucro",
    icon: TrendingUp,
    accent: ACCENT.blue,
    detail:
      "Cada sessão futura alimenta a banca e o Player Evolution — provando, em dinheiro, que a correção funcionou.",
    output: "Impacto do ajuste medido em bb/100 e ROI",
  },
];

export default function EcosystemCycle() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);

  // Auto-rotação do ciclo — pausa quando o usuário assume o controle.
  useEffect(() => {
    if (paused) return undefined;
    const timer = setInterval(
      () => setActive((current) => (current + 1) % steps.length),
      3600
    );
    return () => clearInterval(timer);
  }, [paused]);

  const current = steps[active];

  return (
    <section
      id="ecossistema"
      className="relative overflow-hidden border-y border-hairline py-20 lg:py-28"
    >
      <div aria-hidden="true" className="dot-grid pointer-events-none absolute inset-0" />

      <div className="relative mx-auto max-w-[1280px] px-6">
        <SectionHeading
          eyebrow="Diferencial competitivo"
          title="O ciclo do"
          highlight="ecossistema integrado"
          description="Nenhuma outra ferramenta fecha esse loop. No PokerSync, o dado sai do erro e chega no lucro sem passar por um único arquivo .csv."
        />

        {/* Trilha do ciclo */}
        <motion.div
          variants={staggerContainer(0.09, 0.1)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          className="mt-12 grid gap-3 lg:grid-cols-4"
        >
          {steps.map((step, index) => {
            const isActive = index === active;
            return (
              <motion.div key={step.id} variants={fadeUp} className="relative">
                <button
                  type="button"
                  onClick={() => setActive(index)}
                  onFocus={() => {
                    setPaused(true);
                    setActive(index);
                  }}
                  onBlur={() => setPaused(false)}
                  aria-pressed={isActive}
                  style={{ "--acc": step.accent }}
                  className={`group acc-card acc-lift relative flex w-full cursor-pointer items-center gap-4 rounded-xl border border-hairline bg-surface p-4 text-left lg:flex-col lg:items-start ${
                    isActive ? "is-active" : ""
                  }`}
                >
                  <div
                    aria-hidden="true"
                    className="acc-glow pointer-events-none absolute -left-8 -top-8 size-24 rounded-full blur-2xl"
                  />
                  <span className="acc-border relative flex size-10 shrink-0 items-center justify-center rounded-lg border border-hairline bg-elevated">
                    <step.icon size={18} className="acc-fg text-muted" />
                  </span>
                  <span className="relative min-w-0">
                    <span className="acc-fg block text-[10px] font-bold uppercase tracking-[0.18em] text-muted/50">
                      Etapa {index + 1}
                    </span>
                    <span className="acc-fg mt-1 block text-sm font-semibold text-ink">
                      {step.label}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted/70">{step.action}</span>
                  </span>
                </button>

                {/* Conector para a etapa seguinte */}
                {index < steps.length - 1 ? (
                  <span
                    aria-hidden="true"
                    className="absolute right-[-13px] top-1/2 hidden -translate-y-1/2 text-white/20 lg:block"
                  >
                    <ArrowRight size={16} />
                  </span>
                ) : null}
              </motion.div>
            );
          })}
        </motion.div>

        {/* Painel de detalhe da etapa ativa */}
        <motion.div
          variants={scaleIn}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          style={{ "--acc": current.accent }}
          className="mt-3 overflow-hidden rounded-xl border border-hairline bg-surface p-6 sm:p-8"
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={current.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.35, ease: EASE }}
              className="grid gap-6 lg:grid-cols-[1.4fr_1fr] lg:items-center lg:gap-10"
            >
              <div>
                <p
                  className="text-[11px] font-bold uppercase tracking-[0.2em]"
                  style={{ color: current.accent }}
                >
                  {current.action}
                </p>
                <h3 className="mt-2 text-xl font-bold text-ink sm:text-2xl">{current.label}</h3>
                <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted sm:text-base">
                  {current.detail}
                </p>
              </div>

              <div className="rounded-lg border border-hairline bg-elevated/50 p-4">
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted/60">
                  Saída automática desta etapa
                </p>
                <p className="mt-2 text-sm font-semibold" style={{ color: current.accent }}>
                  {current.output}
                </p>
                <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10">
                  <motion.div
                    key={`${current.id}-bar`}
                    initial={{ width: "0%" }}
                    animate={{ width: "100%" }}
                    transition={{ duration: paused ? 0.6 : 3.6, ease: "linear" }}
                    className="h-full rounded-full"
                    style={{ background: current.accent }}
                  />
                </div>
              </div>
            </motion.div>
          </AnimatePresence>
        </motion.div>

        <motion.p
          variants={fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mx-auto mt-8 flex max-w-3xl items-center justify-center gap-3 rounded-xl border border-hairline bg-surface px-6 py-4 text-center text-sm font-medium text-ink sm:text-base"
        >
          <Repeat size={18} className="shrink-0 text-muted" />
          Estude o erro, crie a estratégia e treine a jogada sem fechar a tela.
        </motion.p>
      </div>
    </section>
  );
}
