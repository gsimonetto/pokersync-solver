import { motion } from "framer-motion";
import { Twitter, Youtube, Instagram, MessageCircle } from "lucide-react";
import Logo from "./ui/Logo.jsx";
import { modules } from "../data/modules.js";
import { fadeUp, staggerContainer, viewportOnce } from "../lib/motion.js";

const columns = [
  {
    title: "Produto",
    // Deriva dos módulos reais — footer não pode divergir do que existe no app.
    links: modules.slice(0, 5).map((m) => ({ label: m.title, href: m.href })),
  },
  {
    title: "Para Times",
    links: [
      { label: "Meu Time", href: "/time" },
      { label: "Painel do coach", href: "/time/painel" },
      { label: "Staking e makeup", href: "#times" },
      { label: "Falar com vendas", href: "#cadastro" },
    ],
  },
  {
    title: "Empresa",
    links: [
      { label: "Planos", href: "#planos" },
      { label: "Ecossistema", href: "#ecossistema" },
      { label: "Entrar", href: "/login" },
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
    <footer className="border-t border-hairline">
      <motion.div
        variants={staggerContainer(0.08)}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="mx-auto max-w-[1280px] px-6 py-14"
      >
        <div className="grid gap-10 lg:grid-cols-[1.4fr_repeat(3,1fr)]">
          <motion.div variants={fadeUp}>
            <Logo className="h-7 w-auto" />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted/70">
              Organize. Estude. Evolua. Um único ecossistema, da teoria ao lucro.
            </p>
            <ul className="mt-6 flex items-center gap-2">
              {socials.map((social) => (
                <li key={social.label}>
                  <a
                    href={social.href}
                    aria-label={social.label}
                    className="flex size-9 items-center justify-center rounded-lg border border-hairline bg-surface text-muted transition-colors hover:border-white/20 hover:bg-elevated hover:text-ink"
                  >
                    <social.icon size={15} />
                  </a>
                </li>
              ))}
            </ul>
          </motion.div>

          {columns.map((column) => (
            <motion.nav key={column.title} variants={fadeUp} aria-label={column.title}>
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink">
                {column.title}
              </h2>
              <ul className="mt-4 space-y-2.5">
                {column.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="text-sm text-muted/70 transition-colors hover:text-ink"
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
          className="mt-12 flex flex-col gap-4 border-t border-hairline pt-8 sm:flex-row sm:items-center sm:justify-between"
        >
          <p className="text-xs text-muted/50">
            © {new Date().getFullYear()} PokerSync. Todos os direitos reservados.
          </p>
          <ul className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted/50">
            <li>
              <a href="#" className="transition-colors hover:text-muted">
                Termos de uso
              </a>
            </li>
            <li>
              <a href="#" className="transition-colors hover:text-muted">
                Política de privacidade
              </a>
            </li>
            <li>
              <a href="#" className="transition-colors hover:text-muted">
                Jogo responsável
              </a>
            </li>
          </ul>
        </motion.div>

        <motion.p variants={fadeUp} className="mt-8 max-w-4xl text-[11px] leading-relaxed text-muted/40">
          O PokerSync é uma ferramenta de estudo, treino e gestão. Não
          garantimos resultados financeiros — desempenho passado não prevê
          desempenho futuro. Conteúdo destinado a maiores de 18 anos. Jogue com
          responsabilidade e apenas com bancas que você pode arriscar.
        </motion.p>
      </motion.div>
    </footer>
  );
}
