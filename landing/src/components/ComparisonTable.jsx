import { motion } from "framer-motion";
import { Check, X } from "lucide-react";
import SectionHeading from "./ui/SectionHeading.jsx";
import Button from "./ui/Button.jsx";
import { fadeUp, scaleIn, staggerContainer, viewportOnce } from "../lib/motion.js";

/**
 * Comparativo de custo financeiro e cognitivo.
 * `fragmented` descreve a stack de 5 ferramentas; `pokersync`, o ecossistema.
 */
const rows = [
  {
    criterion: "Assinaturas mensais",
    fragmented: "5 cobranças separadas (US$ 29 + 19 + 25 + 15 + 22)",
    pokersync: "1 assinatura única, sem cobrança por integração",
  },
  {
    criterion: "Custo mensal estimado",
    fragmented: "US$ 110/mês",
    pokersync: "A partir de US$ 39/mês",
    highlight: true,
  },
  {
    criterion: "Transferência de dados",
    fragmented: "Export/import manual de .csv e .txt entre ferramentas",
    pokersync: "Fluxo nativo: o leak vira range e drill em 1 clique",
  },
  {
    criterion: "Tempo perdido em logística",
    fragmented: "~6h/mês organizando arquivos e planilhas",
    pokersync: "0h — o dado já nasce no lugar certo",
  },
  {
    criterion: "Gestão de banca",
    fragmented: "Planilha manual que quebra a cada mudança de fórmula",
    pokersync: "Banca em tempo real alimentada pelas sessões",
  },
  {
    criterion: "Gestão de time / staking",
    fragmented: "Não existe — vira grupo de WhatsApp e planilha compartilhada",
    pokersync: "Painel 360° com ROI, caixa e ranking interno",
  },
  {
    criterion: "Visão de evolução no longo prazo",
    fragmented: "Fragmentada: cada ferramenta enxerga um pedaço",
    pokersync: "Player Evolution unificado: bb/100, ROI, ABI e tendência",
  },
  {
    criterion: "Constância no estudo",
    fragmented: "Depende só de força de vontade, sem nada medindo",
    pokersync: "Hub de Evolução com XP, missões e ranking",
  },
  {
    criterion: "Curva de aprendizado",
    fragmented: "5 interfaces, 5 lógicas, 5 suportes diferentes",
    pokersync: "Uma interface consistente para toda a rotina",
  },
];

export default function ComparisonTable() {
  return (
    <section id="planos" className="relative py-20 lg:py-28">
      <div className="mx-auto max-w-6xl px-6">
        <SectionHeading
          eyebrow="A conta que ninguém faz"
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
          className="mt-12 hidden overflow-hidden rounded-xl border border-hairline bg-surface md:block"
        >
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">
              Comparativo entre usar cinco softwares isolados e o ecossistema
              unificado PokerSync
            </caption>
            <thead>
              <tr className="border-b border-hairline">
                <th
                  scope="col"
                  className="w-1/4 px-6 py-5 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted/60"
                >
                  Critério
                </th>
                <th
                  scope="col"
                  className="w-[37.5%] px-6 py-5 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted/60"
                >
                  Stack fragmentada
                </th>
                <th
                  scope="col"
                  className="w-[37.5%] border-l border-hairline bg-elevated/50 px-6 py-5 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink"
                >
                  PokerSync
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.criterion} className="border-b border-hairline last:border-0">
                  <th
                    scope="row"
                    className="px-6 py-5 align-top text-sm font-medium text-ink"
                  >
                    {row.criterion}
                  </th>
                  <td className="px-6 py-5 align-top text-sm text-muted/70">
                    <span className="flex gap-2.5">
                      <X size={16} className="mt-0.5 shrink-0 text-negative" />
                      {row.fragmented}
                    </span>
                  </td>
                  <td
                    className={`border-l border-hairline bg-elevated/30 px-6 py-5 align-top text-sm ${
                      row.highlight ? "font-semibold text-ink" : "text-muted"
                    }`}
                  >
                    <span className="flex gap-2.5">
                      <Check size={16} className="mt-0.5 shrink-0 text-positive" />
                      {row.pokersync}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-hairline">
                <th
                  scope="row"
                  className="px-6 py-5 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted/60"
                >
                  Custo real ao ano
                </th>
                <td className="tnum px-6 py-5 text-base font-bold text-muted/60 line-through decoration-negative/60">
                  US$ 1.320 + 72h perdidas
                </td>
                <td className="tnum border-l border-hairline bg-elevated/50 px-6 py-5 text-base font-bold text-ink">
                  US$ 468 · 0h de logística
                </td>
              </tr>
            </tfoot>
          </table>
        </motion.div>

        {/* Mobile: cards empilhados (mantém legibilidade sem scroll horizontal) */}
        <motion.ul
          variants={staggerContainer(0.06, 0.05)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mt-10 space-y-3 md:hidden"
        >
          {rows.map((row) => (
            <motion.li
              key={row.criterion}
              variants={fadeUp}
              className="overflow-hidden rounded-xl border border-hairline bg-surface"
            >
              <p className="border-b border-hairline px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted/60">
                {row.criterion}
              </p>
              <div className="flex gap-2.5 px-4 py-3.5 text-sm text-muted/70">
                <X size={16} className="mt-0.5 shrink-0 text-negative" />
                {row.fragmented}
              </div>
              <div className="flex gap-2.5 border-t border-hairline bg-elevated/40 px-4 py-3.5 text-sm text-ink">
                <Check size={16} className="mt-0.5 shrink-0 text-positive" />
                {row.pokersync}
              </div>
            </motion.li>
          ))}

          <motion.li
            variants={fadeUp}
            className="rounded-xl border border-hairline bg-surface p-5 text-center"
          >
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted/60">
              Custo real ao ano
            </p>
            <p className="tnum mt-2 text-sm text-muted/60 line-through decoration-negative/60">
              US$ 1.320 + 72h perdidas
            </p>
            <p className="tnum mt-1 text-lg font-bold text-ink">US$ 468 · 0h de logística</p>
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
          <p className="text-xs text-muted/60">
            Valores de referência baseados no preço médio das ferramentas isoladas mais usadas no mercado.
          </p>
        </motion.div>
      </div>
    </section>
  );
}
