import { motion } from "framer-motion";
import { ArrowRight, PlayCircle, Sparkles, ShieldCheck } from "lucide-react";
import Button from "./ui/Button.jsx";
import Badge from "./ui/Badge.jsx";
import DashboardMockup from "./DashboardMockup.jsx";
import { fadeUp, staggerContainer } from "../lib/motion.js";

const proofPoints = [
  "14 dias grátis · sem cartão",
  "Migração de planilhas assistida",
  "Cancelamento em 1 clique",
];

export default function Hero() {
  return (
    <section
      id="top"
      className="relative overflow-hidden pb-20 pt-28 sm:pt-32 lg:pb-28 lg:pt-40"
    >
      {/* Camadas de ambiente: grid técnico + halos radiais */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-grid-fade bg-grid [mask-image:radial-gradient(ellipse_70%_55%_at_50%_0%,#000_35%,transparent_100%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-[-14rem] h-[34rem] w-[34rem] -translate-x-1/2 rounded-full bg-emerald-500/15 blur-[120px]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-[-10rem] top-40 h-[26rem] w-[26rem] rounded-full bg-indigo-600/15 blur-[120px]"
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <motion.div
          variants={staggerContainer(0.1, 0.05)}
          initial="hidden"
          animate="visible"
          className="mx-auto flex max-w-4xl flex-col items-center text-center"
        >
          <motion.div variants={fadeUp}>
            <Badge icon={Sparkles}>O fim da roda da fragmentação</Badge>
          </motion.div>

          <motion.h1
            variants={fadeUp}
            className="mt-6 text-4xl font-extrabold leading-[1.08] tracking-tight text-white sm:text-5xl lg:text-6xl xl:text-[4.25rem]"
          >
            Sua rotina de poker.{" "}
            <span className="text-gradient-emerald">
              Tudo integrado em uma só plataforma.
            </span>
          </motion.h1>

          <motion.p
            variants={fadeUp}
            className="mt-6 max-w-2xl text-base leading-relaxed text-slate-400 sm:text-lg lg:text-xl"
          >
            Abandone as 5 assinaturas separadas e as planilhas quebradas. Estude
            ranges, treine drills, revise mãos, gerencie sua banca e acompanhe
            seu time no único ecossistema{" "}
            <span className="font-semibold text-slate-200">100% conectado</span>.
          </motion.p>

          <motion.div
            variants={fadeUp}
            className="mt-9 flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row"
          >
            <Button
              href="#cadastro"
              variant="primary"
              size="lg"
              className="w-full animate-pulse-ring sm:w-auto"
            >
              Experimente o PokerSync Grátis
              <ArrowRight className="h-5 w-5" strokeWidth={2.2} />
            </Button>
            <Button
              href="#ecossistema"
              variant="outline"
              size="lg"
              className="w-full sm:w-auto"
            >
              <PlayCircle className="h-5 w-5" strokeWidth={2} />
              Ver demonstração interativa
            </Button>
          </motion.div>

          <motion.ul
            variants={fadeUp}
            className="mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-slate-500 sm:text-sm"
          >
            {proofPoints.map((point) => (
              <li key={point} className="flex items-center gap-1.5">
                <ShieldCheck className="h-4 w-4 text-emerald-500/70" strokeWidth={2} />
                {point}
              </li>
            ))}
          </motion.ul>
        </motion.div>

        <div className="mt-16 lg:mt-20">
          <DashboardMockup />
        </div>
      </div>
    </section>
  );
}
