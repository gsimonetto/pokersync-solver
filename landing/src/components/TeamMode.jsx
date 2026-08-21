import { motion } from "framer-motion";
import {
  Users,
  Split,
  FileSearch,
  BarChart3,
  Trophy,
  ArrowRight,
} from "lucide-react";
import Button from "./ui/Button.jsx";
import Badge from "./ui/Badge.jsx";
import {
  fadeLeft,
  fadeRight,
  fadeUp,
  staggerContainer,
  viewportOnce,
} from "../lib/motion.js";

const valuePoints = [
  {
    icon: Split,
    title: "Divisão automática de lucros",
    text: "Deals, makeup e percentuais calculados por sessão. O acerto de contas deixa de ser uma noite de planilha.",
  },
  {
    icon: FileSearch,
    title: "Auditoria de mãos do time",
    text: "Revise as mãos de qualquer jogador da cavalariça e devolva a correção como drill atribuído.",
  },
  {
    icon: BarChart3,
    title: "Relatórios técnicos consolidados",
    text: "ROI, EV e volume por jogador, stake e período — em um relatório que o investidor entende.",
  },
  {
    icon: Trophy,
    title: "Ranking interno do time",
    text: "Leaderboard de performance e disciplina de estudo. Competição saudável que sobe o nível do grupo.",
  },
];

const teamRoster = [
  { name: "Jogador A", stake: "NL200", roi: "+18,4%", trend: 82 },
  { name: "Jogador B", stake: "NL100", roi: "+11,2%", trend: 64 },
  { name: "Jogador C", stake: "NL50", roi: "+6,8%", trend: 47 },
  { name: "Jogador D", stake: "NL200", roi: "-2,1%", trend: 24, negative: true },
];

export default function TeamMode() {
  return (
    <section
      id="times"
      className="relative overflow-hidden border-y border-white/5 bg-abyss-950/60 py-20 lg:py-28"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-[-8rem] top-[-6rem] h-[30rem] w-[30rem] rounded-full bg-indigo-600/15 blur-[130px]"
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          {/* Copy comercial B2B */}
          <motion.div
            variants={staggerContainer(0.1)}
            initial="hidden"
            whileInView="visible"
            viewport={viewportOnce}
          >
            <motion.div variants={fadeLeft}>
              <Badge icon={Users}>Modo Time · Staking &amp; Cavalariças</Badge>
            </motion.div>

            <motion.h2
              variants={fadeLeft}
              className="mt-5 text-3xl font-extrabold leading-tight tracking-tight text-white sm:text-4xl lg:text-[2.6rem]"
            >
              Gerencie de 1 a 100+ jogadores{" "}
              <span className="text-gradient-emerald">
                sem perder o controle do ROI.
              </span>
            </motion.h2>

            <motion.p
              variants={fadeLeft}
              className="mt-5 max-w-xl text-base leading-relaxed text-slate-400 sm:text-lg"
            >
              Donos de time, instrutores e investidores operam a cavalariça
              inteira em um painel só: caixa, performance técnica e
              acompanhamento individual no mesmo lugar onde os jogadores já
              estudam.
            </motion.p>

            <motion.ul
              variants={staggerContainer(0.08, 0.15)}
              className="mt-9 grid gap-4 sm:grid-cols-2"
            >
              {valuePoints.map((point) => (
                <motion.li
                  key={point.title}
                  variants={fadeUp}
                  className="glass-panel p-4 transition-colors duration-300 hover:border-indigo-500/30"
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-indigo-500/30 bg-gradient-to-br from-indigo-400/25 to-indigo-600/5 text-indigo-300">
                    <point.icon className="h-4 w-4" strokeWidth={1.8} />
                  </span>
                  <h3 className="mt-3 text-sm font-bold text-white">
                    {point.title}
                  </h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
                    {point.text}
                  </p>
                </motion.li>
              ))}
            </motion.ul>

            <motion.div variants={fadeLeft} className="mt-9">
              <Button href="#cadastro" variant="indigo" size="lg" className="w-full sm:w-auto">
                Escale a gestão da sua cavalariça
                <ArrowRight className="h-5 w-5" strokeWidth={2.2} />
              </Button>
            </motion.div>
          </motion.div>

          {/* Mock do painel do dono de time */}
          <motion.div
            variants={fadeRight}
            initial="hidden"
            whileInView="visible"
            viewport={viewportOnce}
            className="glass-panel overflow-hidden shadow-card"
          >
            <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.02] px-5 py-4">
              <div>
                <p className="text-sm font-bold text-white">Painel do Time</p>
                <p className="text-[11px] text-slate-500">
                  27 jogadores ativos · ciclo de agosto
                </p>
              </div>
              <span className="rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-300">
                Caixa +$18.240
              </span>
            </div>

            <div className="grid grid-cols-3 divide-x divide-white/10 border-b border-white/10">
              {[
                { label: "ROI médio", value: "+12,7%" },
                { label: "Volume", value: "184k mãos" },
                { label: "Makeup", value: "$3.410" },
              ].map((stat) => (
                <div key={stat.label} className="px-4 py-4 text-center">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    {stat.label}
                  </p>
                  <p className="tabular mt-1 text-base font-bold text-white">
                    {stat.value}
                  </p>
                </div>
              ))}
            </div>

            <ul className="divide-y divide-white/[0.06]">
              {teamRoster.map((player, index) => (
                <motion.li
                  key={player.name}
                  initial={{ opacity: 0, x: 16 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={viewportOnce}
                  transition={{ duration: 0.45, delay: 0.15 + index * 0.09 }}
                  className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-white/[0.03]"
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-[11px] font-bold text-slate-300">
                    {player.name.split(" ")[1]}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-slate-200">
                      {player.name}
                    </p>
                    <p className="text-[11px] text-slate-500">{player.stake}</p>
                  </div>
                  <div className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-white/10 sm:block">
                    <motion.div
                      initial={{ width: 0 }}
                      whileInView={{ width: `${player.trend}%` }}
                      viewport={viewportOnce}
                      transition={{ duration: 0.9, delay: 0.35 + index * 0.09 }}
                      className={`h-full rounded-full ${
                        player.negative
                          ? "bg-rose-500/70"
                          : "bg-gradient-to-r from-indigo-500 to-emerald-400"
                      }`}
                    />
                  </div>
                  <span
                    className={`tabular w-16 text-right text-sm font-bold ${
                      player.negative ? "text-rose-400" : "text-emerald-400"
                    }`}
                  >
                    {player.roi}
                  </span>
                </motion.li>
              ))}
            </ul>

            <div className="border-t border-white/10 bg-white/[0.02] px-5 py-3 text-center text-[11px] text-slate-500">
              Split de lucros do ciclo calculado automaticamente
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
