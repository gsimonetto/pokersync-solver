import { motion } from "framer-motion";
import Eyebrow from "./Eyebrow.jsx";
import { fadeUp, staggerContainer, viewportOnce } from "../../lib/motion.js";

/** Cabeçalho padrão de seção: eyebrow + título + descrição, com stagger. */
export default function SectionHeading({
  eyebrow,
  title,
  highlight,
  description,
  align = "center",
  className = "",
}) {
  const alignment =
    align === "left" ? "items-start text-left" : "items-center text-center";

  return (
    <motion.header
      variants={staggerContainer(0.12)}
      initial="hidden"
      whileInView="visible"
      viewport={viewportOnce}
      className={`flex flex-col ${alignment} ${className}`}
    >
      {eyebrow ? (
        <motion.div variants={fadeUp}>
          <Eyebrow>{eyebrow}</Eyebrow>
        </motion.div>
      ) : null}

      <motion.h2
        variants={fadeUp}
        className="mt-3 max-w-3xl text-3xl font-bold tracking-tight text-ink sm:text-4xl"
      >
        {title}{" "}
        {highlight ? <span className="text-muted">{highlight}</span> : null}
      </motion.h2>

      {description ? (
        <motion.p
          variants={fadeUp}
          className="mt-4 max-w-2xl text-sm leading-relaxed text-muted sm:text-base"
        >
          {description}
        </motion.p>
      ) : null}
    </motion.header>
  );
}
