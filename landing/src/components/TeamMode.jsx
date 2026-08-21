import { motion } from "framer-motion";
import { Users, Split, FileSearch, BarChart3, Trophy, ArrowRight } from "lucide-react";
import Button from "./ui/Button.jsx";
import Eyebrow from "./ui/Eyebrow.jsx";
import Chip from "./ui/Chip.jsx";
import Rings from "./ui/Rings.jsx";
import { ACCENT } from "../data/modules.js";
import { fadeLeft, fadeRight, fadeUp, staggerContainer, viewportOnce } from "../lib/motion.js";

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
      className="relative overflow-hidden border-b border-hairline py-20 lg:py-28"
    >
      <div className="relative mx-auto max-w-[1280px] px-6">
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          {/* Copy comercial B2B */}
          <motion.div
            variants={staggerContainer(0.1)}
            initial="hidden"
            whileInView="visible"
            viewport={viewportOnce}
          >
            <motion.div variants={fadeLeft} className="flex items-center gap-3">
              <Eyebrow>Meu Time</Eyebrow>
              <Chip color={ACCENT.indigo} size="sm">
                Staking
              </Chip>
            </motion.div>

            <motion.h2
              variants={fadeLeft}
              className="mt-4 text-3xl font-bold leading-tight tracking-tight text-ink sm:text-4xl"
            >
              Gerencie de 1 a 100+ jogadores{" "}
              <span className="text-muted">sem perder o controle do ROI.</span>
            </motion.h2>

            <motion.p
              variants={fadeLeft}
              className="mt-5 max-w-xl text-sm leading-relaxed text-muted sm:text-base"
            >
              Donos de time, instrutores e investidores operam a cavalariça
              inteira em um painel só: caixa, performance técnica e
              acompanhamento individual no mesmo lugar onde os jogadores já
              estudam.
            </motion.p>

            <motion.ul
              variants={staggerContainer(0.08, 0.15)}
              className="mt-8 grid gap-3 sm:grid-cols-2"
            >
              {valuePoints.map((point) => (
                <motion.li
                  key={point.title}
                  variants={fadeUp}
                  style={{ "--acc": ACCENT.indigo }}
                  className="group acc-card rounded-xl border border-hairline bg-surface p-4"
                >
                  <span className="acc-border flex size-9 items-center justify-center rounded-lg border border-hairline bg-elevated">
                    <point.icon size={16} className="acc-fg text-muted" />
                  </span>
                  <h3 className="acc-fg mt-3 text-sm font-semibold text-ink">{point.title}</h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-muted/80">{point.text}</p>
                </motion.li>
              ))}
            </motion.ul>

            <motion.div variants={fadeLeft} className="mt-8">
              <Button href="#cadastro" variant="primary" size="lg" className="w-full sm:w-auto">
                Escale a gestão da sua cavalariça
                <ArrowRight size={18} />
              </Button>
            </motion.div>
          </motion.div>

          {/* Mock do painel do dono de time */}
          <motion.div
            variants={fadeRight}
            initial="hidden"
            whileInView="visible"
            viewport={viewportOnce}
            className="relative overflow-hidden rounded-xl border border-hairline bg-surface shadow-2xl shadow-black/60"
          >
            <Rings className="opacity-40" />

            <div className="relative flex items-center justify-between border-b border-hairline px-5 py-4">
              <div>
                <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Users size={15} style={{ color: ACCENT.indigo }} />
                  Painel do Time
                </p>
                <p className="mt-0.5 text-[11px] text-muted/70">
                  27 jogadores ativos · ciclo de agosto
                </p>
              </div>
              <Chip color={ACCENT.green} size="sm">
                Caixa +$18.240
              </Chip>
            </div>

            <div className="relative grid grid-cols-3 divide-x divide-hairline border-b border-hairline">
              {[
                { label: "ROI médio", value: "+12,7%" },
                { label: "Volume", value: "184k mãos" },
                { label: "Makeup", value: "$3.410" },
              ].map((stat) => (
                <div key={stat.label} className="px-3 py-4 text-center">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted/60">
                    {stat.label}
                  </p>
                  <p className="tnum mt-1 text-sm font-bold text-ink">{stat.value}</p>
                </div>
              ))}
            </div>

            <ul className="relative divide-y divide-hairline">
              {teamRoster.map((player, index) => (
                <motion.li
                  key={player.name}
                  initial={{ opacity: 0, x: 16 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={viewportOnce}
                  transition={{ duration: 0.45, delay: 0.15 + index * 0.09 }}
                  className="flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-elevated/50"
                >
                  <span className="flex size-8 items-center justify-center rounded-lg border border-hairline bg-elevated text-[11px] font-bold text-muted">
                    {player.name.split(" ")[1]}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{player.name}</p>
                    <p className="text-[11px] text-muted/60">{player.stake}</p>
                  </div>
                  <div className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-white/10 sm:block">
                    <motion.div
                      initial={{ width: 0 }}
                      whileInView={{ width: `${player.trend}%` }}
                      viewport={viewportOnce}
                      transition={{ duration: 0.9, delay: 0.35 + index * 0.09 }}
                      className="h-full rounded-full"
                      style={{
                        background: player.negative ? "var(--color-negative)" : ACCENT.indigo,
                      }}
                    />
                  </div>
                  <span
                    className={`tnum w-16 text-right text-sm font-bold ${
                      player.negative ? "text-negative" : "text-positive"
                    }`}
                  >
                    {player.roi}
                  </span>
                </motion.li>
              ))}
            </ul>

            <div className="relative border-t border-hairline px-5 py-3 text-center text-[11px] text-muted/60">
              Split de lucros do ciclo calculado automaticamente
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
