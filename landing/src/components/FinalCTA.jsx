import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Check, Loader2 } from "lucide-react";
import Eyebrow from "./ui/Eyebrow.jsx";
import Rings from "./ui/Rings.jsx";
import { fadeUp, scaleIn, staggerContainer, viewportOnce } from "../lib/motion.js";

export default function FinalCTA() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | loading | done

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (status !== "idle") return;
    setStatus("loading");
    // Ponto de integração: trocar pelo POST real de captação de leads.
    await new Promise((resolve) => setTimeout(resolve, 900));
    setStatus("done");
  };

  return (
    <section id="cadastro" className="relative px-6 py-20 lg:py-28">
      <motion.div
        variants={scaleIn}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="relative mx-auto max-w-5xl overflow-hidden rounded-2xl border border-hairline bg-surface px-6 py-14 sm:px-12 lg:py-20"
      >
        <div
          aria-hidden="true"
          className="glow-breathe pointer-events-none absolute -left-32 -top-32 size-96 rounded-full bg-white/[0.06] blur-[140px]"
        />
        <div aria-hidden="true" className="dot-grid pointer-events-none absolute inset-0" />
        <Rings className="opacity-60" />

        <motion.div
          variants={staggerContainer(0.1)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="relative flex flex-col items-center text-center"
        >
          <motion.div variants={fadeUp}>
            <Eyebrow>Vagas do onboarding assistido desta safra</Eyebrow>
          </motion.div>

          <motion.h2
            variants={fadeUp}
            className="mt-4 max-w-3xl text-3xl font-bold leading-tight tracking-tight text-ink sm:text-4xl lg:text-5xl"
          >
            Pronto para profissionalizar sua rotina e{" "}
            <span className="text-muted">parar de deixar EV na mesa?</span>
          </motion.h2>

          <motion.p
            variants={fadeUp}
            className="mt-5 max-w-2xl text-sm leading-relaxed text-muted sm:text-base"
          >
            Crie sua conta em menos de 60 segundos, importe suas primeiras
            sessões e veja o ecossistema fechar o ciclo do erro ao lucro.
          </motion.p>

          <motion.form variants={fadeUp} onSubmit={handleSubmit} className="mt-8 w-full max-w-xl">
            <div className="flex flex-col gap-2.5 sm:flex-row">
              <label htmlFor="cta-email" className="sr-only">
                Seu melhor e-mail
              </label>
              <input
                id="cta-email"
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={status !== "idle"}
                placeholder="seu@email.com"
                className="w-full rounded-lg border border-hairline bg-void/60 px-4 py-3 text-sm text-ink transition-colors placeholder:text-muted/40 focus:border-white/25 focus:outline-none disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={status !== "idle"}
                className="inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-lg bg-ink px-6 py-3 text-sm font-semibold text-void shadow-lg shadow-black/40 transition-all hover:bg-white/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/70 focus-visible:ring-offset-2 focus-visible:ring-offset-void disabled:cursor-not-allowed disabled:opacity-50"
              >
                {status === "loading" ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Criando conta…
                  </>
                ) : status === "done" ? (
                  <>
                    <Check size={16} />
                    Acesso enviado
                  </>
                ) : (
                  <>
                    Começar grátis
                    <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>

            <p aria-live="polite" className="mt-4 text-xs text-muted/60">
              {status === "done"
                ? "Enviamos o link de acesso para o seu e-mail. Confira também a caixa de spam."
                : "14 dias grátis · sem cartão de crédito · cancele quando quiser."}
            </p>
          </motion.form>
        </motion.div>
      </motion.div>
    </section>
  );
}
