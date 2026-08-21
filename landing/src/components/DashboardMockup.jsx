import { motion } from "framer-motion";
import { ArrowUpRight, Layers, Target, TrendingUp, Zap } from "lucide-react";
import { ACCENT } from "../data/modules.js";
import { EASE } from "../lib/motion.js";

const kpis = [
  { label: "Win rate", value: "8,4", unit: "bb/100", trend: "+1,9", icon: TrendingUp, acc: ACCENT.cyan },
  { label: "Banca", value: "42.780", unit: "USD", trend: "+12,4%", icon: TrendingUp, acc: ACCENT.blue },
  { label: "Drills", value: "312", unit: "acertos", trend: "+35%", icon: Target, acc: ACCENT.green },
];

/** Curva de EV — pontos fixos, desenhada progressivamente no mount. */
const evPath =
  "M0,84 L34,72 L68,78 L102,58 L136,63 L170,44 L204,49 L238,30 L272,34 L306,14 L340,8";

/**
 * Cores de ação da matriz de ranges — copiadas de TOOL_META/cellBackground
 * (components/ranges/range-grid.tsx do produto). A célula é um gradiente
 * vertical empilhando fold → call → raise pela frequência de cada ação,
 * exatamente como o Construtor de Ranges desenha.
 */
const FOLD_C = "#c4c7c8";
const CALL_C = "#3b82f6";
const RAISE_C = "#22c55e";

function cellBackground({ fold, call }) {
  const foldEnd = fold;
  const callEnd = fold + call;
  return `linear-gradient(to top, ${FOLD_C}22 0%, ${FOLD_C}22 ${foldEnd}%, ${CALL_C} ${foldEnd}%, ${CALL_C} ${callEnd}%, ${RAISE_C} ${callEnd}%, ${RAISE_C} 100%)`;
}

/** Fatia 6x6 de uma range de BTN: [fold%, call%] por mão. */
const rangeGrid = [
  [[0, 0], [0, 0], [0, 0], [0, 15], [0, 40], [20, 50]],
  [[0, 0], [0, 0], [0, 25], [0, 55], [25, 55], [55, 35]],
  [[0, 0], [0, 30], [0, 60], [30, 55], [60, 30], [80, 15]],
  [[0, 20], [0, 55], [35, 50], [65, 30], [85, 12], [100, 0]],
  [[0, 45], [30, 55], [70, 25], [90, 8], [100, 0], [100, 0]],
  [[25, 55], [65, 30], [90, 10], [100, 0], [100, 0], [100, 0]],
];

export default function DashboardMockup() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.9, ease: EASE, delay: 0.35 }}
      className="relative mx-auto w-full max-w-5xl"
    >
      <div className="relative overflow-hidden rounded-xl border border-hairline bg-surface shadow-2xl shadow-black/60">
        {/* Barra superior estilo app */}
        <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
          <div className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-white/15" />
            <span className="size-2.5 rounded-full bg-white/15" />
            <span className="size-2.5 rounded-full bg-white/15" />
          </div>
          <div className="hidden rounded-md border border-hairline bg-void/60 px-4 py-1 text-[11px] text-muted/70 sm:block">
            pokersync.com / modulos
          </div>
          <div
            className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide"
            style={{
              color: ACCENT.green,
              borderColor: `${ACCENT.green}55`,
              background: `${ACCENT.green}1A`,
            }}
          >
            <span className="size-1.5 animate-pulse rounded-full" style={{ background: ACCENT.green }} />
            Sync ativo
          </div>
        </div>

        <div className="grid gap-3 p-4 lg:grid-cols-3">
          {/* Coluna principal: KPIs + curva de EV */}
          <div className="space-y-3 lg:col-span-2">
            <div className="grid grid-cols-3 gap-3">
              {kpis.map((kpi, index) => (
                <motion.div
                  key={kpi.label}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.5, ease: EASE, delay: 0.7 + index * 0.1 }}
                  className="rounded-lg border border-hairline bg-elevated/60 p-3"
                >
                  <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted/70">
                    <kpi.icon size={12} style={{ color: kpi.acc }} />
                    <span className="truncate">{kpi.label}</span>
                  </div>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className="tnum text-lg font-bold text-ink sm:text-xl">{kpi.value}</span>
                    <span className="text-[10px] text-muted/60">{kpi.unit}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-0.5 text-[10px] font-semibold text-positive">
                    <ArrowUpRight size={12} />
                    {kpi.trend}
                  </div>
                </motion.div>
              ))}
            </div>

            <div className="rounded-lg border border-hairline bg-elevated/40 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-ink">Curva de EV acumulado</p>
                  <p className="text-[10px] text-muted/60">Últimas 40 sessões · todos os módulos</p>
                </div>
                <span
                  className="tnum rounded-md px-2 py-1 text-[10px] font-bold"
                  style={{ color: ACCENT.cyan, background: `${ACCENT.cyan}1A` }}
                >
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
                    <stop offset="0%" stopColor={ACCENT.cyan} stopOpacity="0.3" />
                    <stop offset="100%" stopColor={ACCENT.cyan} stopOpacity="0" />
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
                  stroke={ACCENT.cyan}
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 1.6, ease: EASE, delay: 1 }}
                />
                <motion.circle
                  cx="340"
                  cy="8"
                  r="3"
                  fill={ACCENT.cyan}
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ duration: 0.4, delay: 2.4 }}
                />
              </svg>
            </div>
          </div>

          {/* Coluna lateral: range + leak detectado */}
          <div className="space-y-3">
            <div className="rounded-lg border border-hairline bg-elevated/40 p-4">
              <div
                className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide"
                style={{ color: ACCENT.pink }}
              >
                <Layers size={12} />
                Range · BTN vs BB
              </div>
              <div className="mt-3 grid grid-cols-6 gap-1">
                {rangeGrid.flatMap((row, rowIndex) =>
                  row.map(([fold, call], colIndex) => (
                    <motion.span
                      key={`${rowIndex}-${colIndex}`}
                      initial={{ opacity: 0, scale: 0.6 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{
                        duration: 0.3,
                        delay: 1.1 + (rowIndex * 6 + colIndex) * 0.012,
                      }}
                      className="aspect-square rounded-[2px]"
                      style={{ background: cellBackground({ fold, call }) }}
                    />
                  ))
                )}
              </div>
              <div className="mt-3 flex items-center gap-3 text-[9px] text-muted/60">
                {[
                  { label: "Raise", color: RAISE_C },
                  { label: "Call", color: CALL_C },
                  { label: "Fold", color: `${FOLD_C}55` },
                ].map((item) => (
                  <span key={item.label} className="flex items-center gap-1">
                    <span
                      className="size-2 rounded-[2px]"
                      style={{ background: item.color }}
                    />
                    {item.label}
                  </span>
                ))}
              </div>
            </div>

            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: EASE, delay: 1.7 }}
              className="rounded-lg border p-4"
              style={{ borderColor: `${ACCENT.purple}55`, background: `${ACCENT.purple}12` }}
            >
              <div className="flex items-start gap-2.5">
                <span
                  className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md"
                  style={{ background: `${ACCENT.purple}26`, color: ACCENT.purple }}
                >
                  <Zap size={13} />
                </span>
                <div>
                  <p className="text-xs font-semibold text-ink">Leak detectado</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted">
                    Fold excessivo no BB vs 2.5bb. Drill gerado automaticamente.
                  </p>
                </div>
              </div>
              <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: "78%" }}
                  transition={{ duration: 1.2, ease: EASE, delay: 2 }}
                  className="h-full rounded-full"
                  style={{ background: ACCENT.purple }}
                />
              </div>
            </motion.div>
          </div>
        </div>
      </div>

      {/* Card flutuante de reforço */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, ease: EASE, delay: 2.2 }}
        className="absolute -bottom-5 -right-2 hidden rounded-xl border border-hairline bg-elevated px-4 py-3 shadow-2xl shadow-black/60 sm:block lg:-right-6"
      >
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted/70">
          Ferramentas substituídas
        </p>
        <p className="tnum mt-1 text-2xl font-bold text-ink">5 → 1</p>
      </motion.div>
    </motion.div>
  );
}
