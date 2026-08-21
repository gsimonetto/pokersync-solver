import { motion } from "framer-motion";
import { Check, X, Scale, Sparkles } from "lucide-react";
import SectionHeading from "./ui/SectionHeading.jsx";
import Button from "./ui/Button.jsx";
import { fadeUp, scaleIn, staggerContainer, viewportOnce } from "../lib/motion.js";

/**
 * Comparativo de custo financeiro e cognitivo.
 * `fragmented` descreve a stack de 5 ferramentas; `pokersync`, o ecossistema único.
 */
const rows = [
  {
    criterion: "Assinaturas mensais",
    fragmented: "5 cobranças separadas (US$ 29 + 19 + 25 + 15 + 22)",
    pokersync: "1 assinatura única, sem cobrança por integração",
    ok: true,
  },
  {
    criterion: "Custo mensal estimado",
    fragmented: "US$ 110/mês",
    pokersync: "A partir de US$ 39/mês",
    ok: true,
    highlight: true,
  },
  {
    criterion: "Transferência de dados",
    fragmented: "Export/import manual de .csv e .txt entre ferramentas",
    pokersync: "Fluxo nativo: o leak vira range e drill em 1 clique",
    ok: true,
  },
  {
    criterion: "Tempo perdido em logística",
    fragmented: "~6h/mês organizando arquivos e planilhas",
    pokersync: "0h — o dado já nasce no lugar certo",
    ok: true,
  },
  {
    criterion: "Gestão de banca",
    fragmented: "Planilha manual que quebra a cada mudança de fórmula",
    pokersync: "Banca em tempo real alimentada pelas sessões",
    ok: true,
  },
  {
    criterion: "Gestão de time / staking",
    fragmented: "Não existe — vira grupo de WhatsApp e planilha compartilhada",
    pokersync: "Painel 360° com ROI, caixa e ranking interno",
    ok: true,
  },
  {
    criterion: "Visão de evolução no longo prazo",
    fragmented: "Fragmentada: cada ferramenta enxerga um pedaço",
    pokersync: "Dashboard unificado de bb/100, EV, volume e tendência",
    ok: true,
  },
  {
    criterion: "Curva de aprendizado",
    fragmented: "5 interfaces, 5 lógicas, 5 suportes diferentes",
    pokersync: "Uma interface consistente para toda a rotina",
    ok: true,
  },
];

export default function ComparisonTable() {
  return (
    <section id="planos" className="relative py-20 lg:py-28">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-24 h-[26rem] w-[40rem] -translate-x-1/2 rounded-full bg-emerald-600/10 blur-[130px]"
      />

      <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="A conta que ninguém faz"
          eyebrowIcon={Scale}
          title="5 softwares fragmentados"
          highlight="vs. PokerSync"
          description="Some as assinaturas, o tempo de logística e o EV perdido entre uma ferramenta e outra. A stack fragmentada custa muito mais do que parece."
        />

        {/* Desktop: tabela semântica */}
        <motion.div
          variants={scaleIn}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mt-14 hidden overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] backdrop-blur-md md:block"
        >
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">
              Comparativo entre usar cinco softwares isolados e o ecossistema
              unificado PokerSync
            </caption>
            <thead>
              <tr className="border-b border-white/10 bg-abyss-950/60">
                <th
                  scope="col"
                  className="w-1/4 px-6 py-5 text-xs font-bold uppercase tracking-[0.14em] text-slate-500"
                >
                  Critério
                </th>
                <th
                  scope="col"
                  className="w-[37.5%] px-6 py-5 text-xs font-bold uppercase tracking-[0.14em] text-slate-400"
                >
                  Stack fragmentada
                </th>
                <th
                  scope="col"
                  className="w-[37.5%] border-l border-emerald-500/20 bg-emerald-500/[0.05] px-6 py-5 text-xs font-bold uppercase tracking-[0.14em] text-emerald-300"
                >
                  <span className="inline-flex items-center gap-2">
                    <Sparkles className="h-3.5 w-3.5" strokeWidth={2.2} />
                    PokerSync
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.criterion}
                  className="border-b border-white/[0.06] transition-colors last:border-0 hover:bg-white/[0.02]"
                >
                  <th
                    scope="row"
                    className="px-6 py-5 align-top text-sm font-semibold text-slate-200"
                  >
                    {row.criterion}
                  </th>
                  <td className="px-6 py-5 align-top text-sm text-slate-500">
                    <span className="flex gap-2.5">
                      <X
                        className="mt-0.5 h-4 w-4 shrink-0 text-rose-500/70"
                        strokeWidth={2.2}
                      />
                      {row.fragmented}
                    </span>
                  </td>
                  <td
                    className={`border-l border-emerald-500/20 px-6 py-5 align-top text-sm ${
                      row.highlight
                        ? "bg-emerald-500/[0.07] font-semibold text-emerald-200"
                        : "bg-emerald-500/[0.03] text-slate-300"
                    }`}
                  >
                    <span className="flex gap-2.5">
                      <Check
                        className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400"
                        strokeWidth={2.4}
                      />
                      {row.pokersync}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-white/10 bg-abyss-950/60">
                <th
                  scope="row"
                  className="px-6 py-5 text-sm font-bold uppercase tracking-wider text-slate-400"
                >
                  Custo real ao ano
                </th>
                <td className="tabular px-6 py-5 text-lg font-bold text-slate-400 line-through decoration-rose-500/50">
                  US$ 1.320 + 72h perdidas
                </td>
                <td className="tabular border-l border-emerald-500/20 bg-emerald-500/[0.07] px-6 py-5 text-lg font-extrabold text-emerald-300">
                  US$ 468 · 0h de logística
                </td>
              </tr>
            </tfoot>
          </table>
        </motion.div>

        {/* Mobile: cards empilhados (mantém legibilidade sem scroll horizontal) */}
        <motion.ul
          variants={staggerContainer(0.07, 0.05)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mt-12 space-y-3 md:hidden"
        >
          {rows.map((row) => (
            <motion.li
              key={row.criterion}
              variants={fadeUp}
              className="glass-panel overflow-hidden"
            >
              <p className="border-b border-white/10 bg-abyss-950/50 px-4 py-3 text-xs font-bold uppercase tracking-[0.12em] text-slate-400">
                {row.criterion}
              </p>
              <div className="flex gap-2.5 px-4 py-3.5 text-sm text-slate-500">
                <X className="mt-0.5 h-4 w-4 shrink-0 text-rose-500/70" strokeWidth={2.2} />
                {row.fragmented}
              </div>
              <div className="flex gap-2.5 border-t border-emerald-500/20 bg-emerald-500/[0.05] px-4 py-3.5 text-sm text-slate-200">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" strokeWidth={2.4} />
                {row.pokersync}
              </div>
            </motion.li>
          ))}

          <motion.li
            variants={fadeUp}
            className="glass-panel-emerald p-5 text-center"
          >
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
              Custo real ao ano
            </p>
            <p className="tabular mt-2 text-sm text-slate-500 line-through decoration-rose-500/50">
              US$ 1.320 + 72h perdidas
            </p>
            <p className="tabular mt-1 text-xl font-extrabold text-emerald-300">
              US$ 468 · 0h de logística
            </p>
          </motion.li>
        </motion.ul>

        <motion.div
          variants={fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mt-10 flex flex-col items-center gap-3 text-center"
        >
          <Button href="#cadastro" variant="primary" size="lg" className="w-full sm:w-auto">
            Trocar 5 assinaturas por 1
          </Button>
          <p className="text-xs text-slate-500">
            Valores de referência baseados no preço médio das ferramentas isoladas mais usadas no mercado.
          </p>
        </motion.div>
      </div>
    </section>
  );
}
