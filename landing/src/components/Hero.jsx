import { motion } from "framer-motion";
import { ArrowRight, PlayCircle, Check } from "lucide-react";
import Button from "./ui/Button.jsx";
import Eyebrow from "./ui/Eyebrow.jsx";
import DashboardMockup from "./DashboardMockup.jsx";
import { fadeUp, staggerContainer } from "../lib/motion.js";

const proofPoints = [
  "14 dias grátis · sem cartão",
  "Migração de planilhas assistida",
  "Cancelamento em 1 clique",
];

export default function Hero() {
  return (
    <section id="top" className="relative overflow-hidden pb-20 pt-28 lg:pb-28 lg:pt-36">
      {/* Ambiente da marca: trama de pontos + blobs brancos difusos */}
      <div aria-hidden="true" className="dot-grid pointer-events-none absolute inset-0" />
      <div
        aria-hidden="true"
        className="glow-breathe pointer-events-none absolute -top-40 left-1/2 size-[36rem] -translate-x-1/2 rounded-full bg-white/[0.06] blur-[140px]"
      />

      <div className="relative mx-auto max-w-[1280px] px-6">
        <motion.div
          variants={staggerContainer(0.1, 0.05)}
          initial="hidden"
          animate="visible"
          className="mx-auto flex max-w-3xl flex-col items-center text-center"
        >
          <motion.div variants={fadeUp}>
            <Eyebrow>O fim da roda da fragmentação</Eyebrow>
          </motion.div>

          <motion.h1
            variants={fadeUp}
            className="mt-4 text-[2rem] font-bold leading-[1.12] tracking-tight text-ink sm:text-5xl"
          >
            Sua rotina de poker.{" "}
            <span className="text-muted">Tudo integrado em uma só plataforma.</span>
          </motion.h1>

          <motion.p
            variants={fadeUp}
            className="mt-6 max-w-2xl text-base leading-relaxed text-muted sm:text-lg"
          >
            Abandone as 5 assinaturas separadas e as planilhas quebradas. Estude
            ranges, treine drills, revise mãos, gerencie sua banca e acompanhe
            seu time no único ecossistema{" "}
            <span className="font-semibold text-ink">100% conectado</span>.
          </motion.p>

          <motion.div
            variants={fadeUp}
            className="mt-8 flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row"
          >
            <Button href="#cadastro" variant="primary" size="lg" className="w-full sm:w-auto">
              Experimente o PokerSync Grátis
              <ArrowRight size={18} />
            </Button>
            <Button href="#ecossistema" variant="outline" size="lg" className="w-full sm:w-auto">
              <PlayCircle size={18} />
              Ver demonstração interativa
            </Button>
          </motion.div>

          <motion.ul
            variants={fadeUp}
            className="mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-muted/70"
          >
            {proofPoints.map((point) => (
              <li key={point} className="flex items-center gap-1.5">
                <Check size={14} className="text-positive" />
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
