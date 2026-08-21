import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Menu, X, ArrowRight } from "lucide-react";
import Logo from "./ui/Logo.jsx";
import Button from "./ui/Button.jsx";
import { EASE } from "../lib/motion.js";

const navLinks = [
  { label: "Módulos", href: "#modulos" },
  { label: "Ecossistema", href: "#ecossistema" },
  { label: "Para Times", href: "#times" },
  { label: "Planos", href: "#planos" },
];

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Trava o scroll do body enquanto o drawer mobile está aberto.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  useEffect(() => {
    const onKeyDown = (event) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${
        scrolled
          ? "border-b border-white/10 bg-abyss-900/80 backdrop-blur-xl"
          : "border-b border-transparent bg-transparent"
      }`}
    >
      <nav
        aria-label="Navegação principal"
        className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:h-[72px] lg:px-8"
      >
        <Logo />

        <ul className="hidden items-center gap-1 lg:flex">
          {navLinks.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                className="relative rounded-lg px-4 py-2 text-sm font-medium text-slate-400 transition-colors duration-200 hover:text-white"
              >
                {link.label}
              </a>
            </li>
          ))}
        </ul>

        <div className="hidden items-center gap-3 lg:flex">
          <Button href="#login" variant="ghost" size="sm">
            Entrar
          </Button>
          <Button href="#cadastro" variant="primary" size="sm">
            Iniciar Teste Grátis
            <ArrowRight className="h-4 w-4" strokeWidth={2.2} />
          </Button>
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-drawer"
          aria-label={open ? "Fechar menu" : "Abrir menu"}
          className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-slate-200 backdrop-blur-md transition-colors hover:border-emerald-500/30 hover:text-white lg:hidden"
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>

      <AnimatePresence>
        {open ? (
          <>
            <motion.div
              key="overlay"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 top-16 z-40 bg-abyss-950/70 backdrop-blur-sm lg:hidden"
              aria-hidden="true"
            />
            <motion.div
              key="drawer"
              id="mobile-drawer"
              initial={{ opacity: 0, y: -16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -16 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="absolute inset-x-0 top-16 z-50 mx-3 rounded-2xl border border-white/10 bg-abyss-850/95 p-5 shadow-card backdrop-blur-xl lg:hidden"
            >
              <ul className="flex flex-col gap-1">
                {navLinks.map((link) => (
                  <li key={link.href}>
                    <a
                      href={link.href}
                      onClick={() => setOpen(false)}
                      className="flex items-center justify-between rounded-xl px-4 py-3 text-base font-medium text-slate-300 transition-colors hover:bg-white/5 hover:text-white"
                    >
                      {link.label}
                      <ArrowRight className="h-4 w-4 text-slate-600" />
                    </a>
                  </li>
                ))}
              </ul>

              <div className="mt-5 flex flex-col gap-3 border-t border-white/10 pt-5">
                <Button
                  href="#login"
                  variant="outline"
                  size="md"
                  onClick={() => setOpen(false)}
                >
                  Entrar
                </Button>
                <Button
                  href="#cadastro"
                  variant="primary"
                  size="md"
                  onClick={() => setOpen(false)}
                >
                  Iniciar Teste Grátis
                  <ArrowRight className="h-4 w-4" strokeWidth={2.2} />
                </Button>
              </div>
            </motion.div>
          </>
        ) : null}
      </AnimatePresence>
    </header>
  );
}
