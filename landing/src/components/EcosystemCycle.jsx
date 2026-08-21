import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ScanSearch,
  Grid3x3,
  Target,
  Wallet,
  ArrowRight,
  Repeat,
  Workflow,
} from "lucide-react";
import SectionHeading from "./ui/SectionHeading.jsx";
import {
  EASE,
  fadeUp,
  scaleIn,
  staggerContainer,
  viewportOnce,
} from "../lib/motion.js";

const steps = [
  {
    id: "revisor",
    label: "Revisor de Mãos",
    action: "Detecta o leak",
    icon: ScanSearch,
    detail:
      "Importa a sessão, cruza cada decisão com a solução GTO e marca automaticamente os spots onde você deixou EV na mesa.",
    output: "3 leaks classificados por custo em bb/100",
  },
  {
    id: "ranges",
    label: "Construtor de Ranges",
    action: "Ajusta a estratégia",
    icon: Grid3x3,
    detail:
      "O leak abre a matriz exata do spot. Você edita frequências combo a combo e salva a correção como range oficial.",
    output: "Range corrigida versionada no seu perfil",
  },
  {
    id: "treino",
    label: "Modo Treino",
    action: "Pratica o cenário",
    icon: Target,
    detail:
      "A range corrigida vira um drill interativo com repetição espaçada, até a decisão certa virar reflexo na mesa.",
    output: "Drill gerado sem nenhuma exportação manual",
  },
  {
    id: "banca",
    label: "Banca & Evolution",
    action: "Acompanha o lucro",
    icon: Wallet,
    detail:
      "Cada sessão futura alimenta a banca e o dashboard de evolução — provando, em dinheiro, que a correção funcionou.",
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
      className="relative overflow-hidden border-y border-white/5 bg-abyss-950/60 py-20 lg:py-28"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 h-[30rem] w-[60rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-600/10 blur-[130px]"
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="Diferencial competitivo"
          eyebrowIcon={Workflow}
          title="O ciclo do"
          highlight="ecossistema integrado"
          description="Nenhuma outra ferramenta fecha esse loop. No PokerSync, o dado sai do erro e chega no lucro sem passar por um único arquivo .csv."
        />

        {/* Trilha do ciclo */}
        <motion.div
          variants={staggerContainer(0.1, 0.1)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          className="mt-14 grid gap-3 lg:grid-cols-[repeat(4,minmax(0,1fr))] lg:gap-0"
        >
          {steps.map((step, index) => {
            const isActive = index === active;
            return (
              <motion.div
                key={step.id}
                variants={fadeUp}
                className="relative flex items-center gap-3 lg:flex-col lg:gap-0"
              >
                <button
                  type="button"
                  onClick={() => setActive(index)}
                  onFocus={() => {
                    setPaused(true);
                    setActive(index);
                  }}
                  onBlur={() => setPaused(false)}
                  aria-pressed={isActive}
                  className={`group relative z-10 flex w-full items-center gap-4 rounded-2xl border p-4 text-left backdrop-blur-md transition-all duration-500 lg:mx-2 lg:flex-col lg:items-center lg:gap-3 lg:p-5 lg:text-center ${
                    isActive
                      ? "border-emerald-500/40 bg-emerald-500/[0.08] shadow-glow"
                      : "border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]"
                  }`}
                >
                  <span
                    className={`relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border transition-all duration-500 ${
                      isActive
                        ? "border-emerald-500/40 bg-gradient-to-br from-emerald-400/30 to-emerald-600/10 text-emerald-300"
                        : "border-white/10 bg-white/[0.04] text-slate-400 group-hover:text-slate-200"
                    }`}
                  >
                    <step.icon className="h-5 w-5" strokeWidth={1.8} />
                    {isActive ? (
                      <motion.span
                        layoutId="cycle-halo"
                        className="absolute inset-0 -z-10 rounded-xl bg-emerald-500/25 blur-lg"
                      />
                    ) : null}
                  </span>

                  <span className="min-w-0">
                    <span
                      className={`block text-[10px] font-bold uppercase tracking-[0.14em] transition-colors ${
                        isActive ? "text-emerald-400" : "text-slate-600"
                      }`}
                    >
                      Etapa {index + 1}
                    </span>
                    <span className="mt-1 block text-sm font-bold text-white">
                      {step.label}
                    </span>
                    <span className="mt-0.5 block text-xs text-slate-500">
                      {step.action}
                    </span>
                  </span>
                </button>

                {/* Conector: seta vertical no mobile, linha animada no desktop */}
                {index < steps.length - 1 ? (
                  <>
                    <span
                      aria-hidden="true"
                      className="absolute -bottom-3 left-9 z-0 hidden h-3 w-px bg-gradient-to-b from-emerald-500/40 to-transparent max-lg:block"
                    />
                    <span
                      aria-hidden="true"
                      className="absolute right-[-14px] top-1/2 hidden -translate-y-1/2 text-emerald-500/50 lg:block"
                    >
                      <ArrowRight className="h-5 w-5" strokeWidth={2} />
                    </span>
                  </>
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
          className="glass-panel-emerald mt-6 overflow-hidden p-6 sm:p-8"
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={current.id}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -14 }}
              transition={{ duration: 0.35, ease: EASE }}
              className="grid gap-6 lg:grid-cols-[1.4fr_1fr] lg:items-center lg:gap-10"
            >
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-emerald-400">
                  {current.action}
                </p>
                <h3 className="mt-2 text-xl font-bold text-white sm:text-2xl">
                  {current.label}
                </h3>
                <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-base">
                  {current.detail}
                </p>
              </div>

              <div className="rounded-xl border border-white/10 bg-abyss-950/60 p-4">
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
                  Saída automática desta etapa
                </p>
                <p className="mt-2 text-sm font-semibold text-emerald-300">
                  {current.output}
                </p>
                <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10">
                  <motion.div
                    key={`${current.id}-bar`}
                    initial={{ width: "0%" }}
                    animate={{ width: "100%" }}
                    transition={{ duration: paused ? 0.6 : 3.6, ease: "linear" }}
                    className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400"
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
          className="mx-auto mt-10 flex max-w-3xl items-center justify-center gap-3 rounded-2xl border border-indigo-500/20 bg-indigo-500/[0.06] px-6 py-4 text-center text-sm font-semibold text-slate-200 backdrop-blur-md sm:text-base"
        >
          <Repeat className="h-5 w-5 shrink-0 text-indigo-400" strokeWidth={2} />
          Estude o erro, crie a estratégia e treine a jogada sem fechar a tela.
        </motion.p>
      </div>
    </section>
  );
}
