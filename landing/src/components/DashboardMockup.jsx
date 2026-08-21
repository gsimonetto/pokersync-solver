import { motion } from "framer-motion";
import {
  ArrowUpRight,
  Grid3x3,
  Target,
  Wallet,
  Zap,
  TrendingUp,
} from "lucide-react";
import { EASE } from "../lib/motion.js";

const kpis = [
  { label: "Win rate", value: "8,4", unit: "bb/100", trend: "+1,9", icon: TrendingUp },
  { label: "Banca", value: "42.780", unit: "USD", trend: "+12,4%", icon: Wallet },
  { label: "Drills", value: "312", unit: "acertos", trend: "+35%", icon: Target },
];

/** Curva de EV do mockup — pontos fixos, desenhados progressivamente no mount. */
const evPath =
  "M0,84 L34,72 L68,78 L102,58 L136,63 L170,44 L204,49 L238,30 L272,34 L306,14 L340,8";

/** Matriz 6x6 representando o Construtor de Ranges (intensidade = frequência). */
const rangeGrid = [
  [3, 3, 3, 3, 2, 2],
  [3, 3, 3, 2, 2, 1],
  [3, 3, 2, 2, 1, 1],
  [2, 2, 2, 1, 1, 0],
  [2, 2, 1, 1, 0, 0],
  [1, 1, 1, 0, 0, 0],
];

const cellTone = [
  "bg-white/[0.04]",
  "bg-indigo-500/30",
  "bg-emerald-500/40",
  "bg-emerald-400/80",
];

export default function DashboardMockup() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 40, rotateX: 12 }}
      animate={{ opacity: 1, y: 0, rotateX: 0 }}
      transition={{ duration: 1, ease: EASE, delay: 0.35 }}
      style={{ perspective: 1200 }}
      className="relative mx-auto w-full max-w-5xl"
    >
      {/* Halo de fundo */}
      <div
        className="absolute -inset-x-10 -top-10 bottom-0 rounded-[3rem] bg-emerald-500/10 blur-3xl"
        aria-hidden="true"
      />

      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-abyss-850/80 shadow-card backdrop-blur-xl">
        {/* Barra superior estilo app */}
        <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.02] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-rose-500/60" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-500/60" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/60" />
          </div>
          <div className="hidden rounded-lg border border-white/10 bg-abyss-900/80 px-4 py-1 text-[11px] font-medium text-slate-500 sm:block">
            app.pokersync.com / dashboard
          </div>
          <div className="flex items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-300">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            Sync ativo
          </div>
        </div>

        <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-3">
          {/* Coluna principal: KPIs + curva de EV */}
          <div className="space-y-4 lg:col-span-2">
            <div className="grid grid-cols-3 gap-3">
              {kpis.map((kpi, index) => (
                <motion.div
                  key={kpi.label}
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, ease: EASE, delay: 0.75 + index * 0.1 }}
                  className="rounded-xl border border-white/10 bg-white/[0.03] p-3"
                >
                  <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    <kpi.icon className="h-3 w-3" strokeWidth={2} />
                    <span className="truncate">{kpi.label}</span>
                  </div>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className="tabular text-lg font-bold text-white sm:text-xl">
                      {kpi.value}
                    </span>
                    <span className="text-[10px] text-slate-500">{kpi.unit}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-0.5 text-[10px] font-semibold text-emerald-400">
                    <ArrowUpRight className="h-3 w-3" strokeWidth={2.5} />
                    {kpi.trend}
                  </div>
                </motion.div>
              ))}
            </div>

            <div className="rounded-xl border border-emerald-500/20 bg-gradient-to-b from-emerald-500/[0.06] to-transparent p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-white">Curva de EV acumulado</p>
                  <p className="text-[10px] text-slate-500">Últimas 40 sessões · todos os módulos</p>
                </div>
                <span className="tabular rounded-md bg-emerald-500/15 px-2 py-1 text-[10px] font-bold text-emerald-300">
                  +18,2 bi
                </span>
              </div>

              <svg
                viewBox="0 0 340 96"
                className="mt-3 h-24 w-full"
                fill="none"
                role="img"
                aria-label="Gráfico de EV acumulado em tendência de alta"
              >
                <defs>
                  <linearGradient id="ev-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <motion.path
                  d={`${evPath} L340,96 L0,96 Z`}
                  fill="url(#ev-fill)"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.8, delay: 1.8 }}
                />
                <motion.path
                  d={evPath}
                  stroke="#10b981"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 1.6, ease: EASE, delay: 1 }}
                />
                <motion.circle
                  cx="340"
                  cy="8"
                  r="3.5"
                  fill="#10b981"
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ duration: 0.4, delay: 2.4 }}
                />
              </svg>
            </div>
          </div>

          {/* Coluna lateral: range + fluxo automático */}
          <div className="space-y-4">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-indigo-300">
                <Grid3x3 className="h-3 w-3" strokeWidth={2} />
                Range · BTN vs BB
              </div>
              <div className="mt-3 grid grid-cols-6 gap-1">
                {rangeGrid.flatMap((row, rowIndex) =>
                  row.map((tone, colIndex) => (
                    <motion.span
                      key={`${rowIndex}-${colIndex}`}
                      initial={{ opacity: 0, scale: 0.6 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{
                        duration: 0.3,
                        delay: 1.1 + (rowIndex * 6 + colIndex) * 0.012,
                      }}
                      className={`aspect-square rounded-[3px] ${cellTone[tone]}`}
                    />
                  ))
                )}
              </div>
            </div>

            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: EASE, delay: 1.7 }}
              className="rounded-xl border border-emerald-500/25 bg-emerald-500/[0.07] p-4"
            >
              <div className="flex items-start gap-2.5">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
                  <Zap className="h-3.5 w-3.5" strokeWidth={2.4} />
                </span>
                <div>
                  <p className="text-xs font-semibold text-white">Leak detectado</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                    Fold excessivo no BB vs 2.5bb. Drill gerado automaticamente.
                  </p>
                </div>
              </div>
              <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: "78%" }}
                  transition={{ duration: 1.2, ease: EASE, delay: 2 }}
                  className="h-full rounded-full bg-emerald-400"
                />
              </div>
            </motion.div>
          </div>
        </div>
      </div>

      {/* Card flutuante de reforço */}
      <motion.div
        initial={{ opacity: 0, scale: 0.85 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, ease: EASE, delay: 2.2 }}
        className="absolute -bottom-6 -right-2 hidden animate-float rounded-2xl border border-indigo-500/25 bg-abyss-850/90 px-4 py-3 shadow-glow-indigo backdrop-blur-xl sm:block lg:-right-8"
      >
        <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-300">
          Ferramentas substituídas
        </p>
        <p className="tabular mt-1 text-2xl font-extrabold text-white">5 → 1</p>
      </motion.div>
    </motion.div>
  );
}
