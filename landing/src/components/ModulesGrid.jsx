import { motion } from "framer-motion";
import SectionHeading from "./ui/SectionHeading.jsx";
import ModuleCard from "./ModuleCard.jsx";
import { modules } from "../data/modules.js";
import { staggerContainer, viewportOnce } from "../lib/motion.js";

export default function ModulesGrid() {
  return (
    <section id="modulos" className="relative py-20 lg:py-28">
      <div className="mx-auto max-w-[1280px] px-6">
        <SectionHeading
          eyebrow={`${modules.length} módulos · 1 assinatura`}
          title="Tudo o que sua rotina exige,"
          highlight="nativamente conectado"
          description="Cada módulo resolve uma dor específica — e conversa com os outros por padrão, não por integração paga."
        />

        <motion.div
          variants={staggerContainer(0.07, 0.1)}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mt-12 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
        >
          {modules.map((module) => (
            <ModuleCard key={module.key} module={module} />
          ))}
        </motion.div>
      </div>
    </section>
  );
}
