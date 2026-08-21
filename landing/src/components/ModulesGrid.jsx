import { motion } from "framer-motion";
import { LayoutGrid } from "lucide-react";
import SectionHeading from "./ui/SectionHeading.jsx";
import ModuleCard from "./ModuleCard.jsx";
import { modules } from "../data/modules.js";
import { staggerContainer, viewportOnce } from "../lib/motion.js";

export default function ModulesGrid() {
  return (
    <section id="modulos" className="relative py-20 lg:py-28">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-[-12rem] top-1/3 h-[24rem] w-[24rem] rounded-full bg-emerald-600/10 blur-[130px]"
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionHeading
          eyebrow="6 módulos · 1 assinatura"
          eyebrowIcon={LayoutGrid}
          title="Tudo o que sua rotina exige,"
          highlight="nativamente conectado"
          description="Cada módulo resolve uma dor específica — e conversa com os outros cinco por padrão, não por integração paga."
        />

        <motion.div
          variants={staggerContainer(0.09, 0.1)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mt-14 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3"
        >
          {modules.map((module) => (
            <ModuleCard key={module.id} module={module} />
          ))}
        </motion.div>
      </div>
    </section>
  );
}
