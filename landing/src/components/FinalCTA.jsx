import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, Flame, Loader2 } from "lucide-react";
import Badge from "./ui/Badge.jsx";
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
    <section id="cadastro" className="relative px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
      <motion.div
        variants={scaleIn}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="relative mx-auto max-w-5xl overflow-hidden rounded-3xl border border-emerald-500/25 bg-gradient-to-b from-emerald-500/[0.09] via-abyss-850/60 to-abyss-900 px-6 py-14 backdrop-blur-xl sm:px-12 lg:py-20"
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 -top-40 h-80 bg-emerald-500/20 blur-[110px]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-grid-fade bg-grid opacity-40 [mask-image:radial-gradient(ellipse_60%_60%_at_50%_50%,#000,transparent_100%)]"
        />

        <motion.div
          variants={staggerContainer(0.1)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="relative flex flex-col items-center text-center"
        >
          <motion.div variants={fadeUp}>
            <Badge
              icon={Flame}
              className="border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
            >
              Vagas do onboarding assistido desta safra
            </Badge>
          </motion.div>

          <motion.h2
            variants={fadeUp}
            className="mt-6 max-w-3xl text-3xl font-extrabold leading-tight tracking-tight text-white sm:text-4xl lg:text-5xl"
          >
            Pronto para profissionalizar sua rotina e{" "}
            <span className="text-gradient-emerald">
              parar de deixar EV na mesa?
            </span>
          </motion.h2>

          <motion.p
            variants={fadeUp}
            className="mt-5 max-w-2xl text-base leading-relaxed text-slate-400 sm:text-lg"
          >
            Crie sua conta em menos de 60 segundos, importe suas primeiras
            sessões e veja o ecossistema fechar o ciclo do erro ao lucro.
          </motion.p>

          <motion.form
            variants={fadeUp}
            onSubmit={handleSubmit}
            className="mt-9 w-full max-w-xl"
          >
            <div className="flex flex-col gap-3 sm:flex-row">
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
                className="w-full rounded-xl border border-white/15 bg-abyss-950/70 px-5 py-3.5 text-base text-white placeholder:text-slate-600 backdrop-blur-md transition-colors focus:border-emerald-500/50 focus:outline-none focus:ring-2 focus:ring-emerald-500/25 disabled:opacity-60"
              />
              <button
                type="submit"
                disabled={status !== "idle"}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-emerald-500 px-7 py-3.5 text-base font-semibold text-abyss-950 shadow-glow transition-all duration-300 hover:bg-emerald-400 hover:shadow-glow-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-abyss-900 active:scale-[0.98] disabled:opacity-70"
              >
                {status === "loading" ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin" strokeWidth={2.2} />
                    Criando conta…
                  </>
                ) : status === "done" ? (
                  <>
                    <CheckCircle2 className="h-5 w-5" strokeWidth={2.2} />
                    Acesso enviado
                  </>
                ) : (
                  <>
                    Começar grátis
                    <ArrowRight className="h-5 w-5" strokeWidth={2.2} />
                  </>
                )}
              </button>
            </div>

            <p
              aria-live="polite"
              className="mt-4 text-xs text-slate-500"
            >
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
