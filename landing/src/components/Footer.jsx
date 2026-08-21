import { motion } from "framer-motion";
import { Twitter, Youtube, Instagram, MessageCircle } from "lucide-react";
import Logo from "./ui/Logo.jsx";
import { fadeUp, staggerContainer, viewportOnce } from "../lib/motion.js";

const columns = [
  {
    title: "Produto",
    links: [
      { label: "Modo Treino", href: "#treino" },
      { label: "Gestor de Banca", href: "#banca" },
      { label: "Revisor de Mãos", href: "#revisor" },
      { label: "Construtor de Ranges", href: "#ranges" },
      { label: "Player Evolution", href: "#evolution" },
    ],
  },
  {
    title: "Para Times",
    links: [
      { label: "Modo Time", href: "#times" },
      { label: "Staking e makeup", href: "#times" },
      { label: "Relatórios de ROI", href: "#times" },
      { label: "Falar com vendas", href: "#cadastro" },
    ],
  },
  {
    title: "Empresa",
    links: [
      { label: "Planos", href: "#planos" },
      { label: "Ecossistema", href: "#ecossistema" },
      { label: "Blog e estudos", href: "#" },
      { label: "Suporte", href: "#" },
    ],
  },
];

const socials = [
  { label: "Twitter/X", icon: Twitter, href: "#" },
  { label: "YouTube", icon: Youtube, href: "#" },
  { label: "Instagram", icon: Instagram, href: "#" },
  { label: "Discord", icon: MessageCircle, href: "#" },
];

export default function Footer() {
  return (
    <footer className="relative border-t border-white/10 bg-abyss-950/80">
      <motion.div
        variants={staggerContainer(0.08)}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8 lg:py-16"
      >
        <div className="grid gap-10 lg:grid-cols-[1.4fr_repeat(3,1fr)]">
          <motion.div variants={fadeUp}>
            <Logo />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-slate-500">
              Um único ecossistema. Sem atrito. Da teoria ao lucro.
            </p>
            <ul className="mt-6 flex items-center gap-2">
              {socials.map((social) => (
                <li key={social.label}>
                  <a
                    href={social.href}
                    aria-label={social.label}
                    className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-slate-400 transition-all duration-300 hover:border-emerald-500/30 hover:text-emerald-300"
                  >
                    <social.icon className="h-4 w-4" strokeWidth={1.8} />
                  </a>
                </li>
              ))}
            </ul>
          </motion.div>

          {columns.map((column) => (
            <motion.nav key={column.title} variants={fadeUp} aria-label={column.title}>
              <h2 className="text-xs font-bold uppercase tracking-[0.14em] text-white">
                {column.title}
              </h2>
              <ul className="mt-4 space-y-2.5">
                {column.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="text-sm text-slate-500 transition-colors hover:text-emerald-300"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </motion.nav>
          ))}
        </div>

        <motion.div
          variants={fadeUp}
          className="mt-12 flex flex-col gap-4 border-t border-white/10 pt-8 sm:flex-row sm:items-center sm:justify-between"
        >
          <p className="text-xs text-slate-600">
            © {new Date().getFullYear()} PokerSync. Todos os direitos reservados.
          </p>
          <ul className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-slate-600">
            <li>
              <a href="#" className="transition-colors hover:text-slate-400">
                Termos de uso
              </a>
            </li>
            <li>
              <a href="#" className="transition-colors hover:text-slate-400">
                Política de privacidade
              </a>
            </li>
            <li>
              <a href="#" className="transition-colors hover:text-slate-400">
                Jogo responsável
              </a>
            </li>
          </ul>
        </motion.div>

        <motion.p
          variants={fadeUp}
          className="mt-8 max-w-4xl text-[11px] leading-relaxed text-slate-700"
        >
          O PokerSync é uma ferramenta de estudo, treino e gestão. Não
          garantimos resultados financeiros — desempenho passado não prevê
          desempenho futuro. Conteúdo destinado a maiores de 18 anos. Jogue com
          responsabilidade e apenas com bancas que você pode arriscar.
        </motion.p>
      </motion.div>
    </footer>
  );
}
