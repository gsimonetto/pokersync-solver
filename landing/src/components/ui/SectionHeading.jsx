import { motion } from "framer-motion";
import Badge from "./Badge.jsx";
import { fadeUp, staggerContainer, viewportOnce } from "../../lib/motion.js";

/** Cabeçalho padrão de seção: eyebrow + título + subtítulo, com stagger no scroll. */
export default function SectionHeading({
  eyebrow,
  eyebrowIcon,
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
          <Badge icon={eyebrowIcon}>{eyebrow}</Badge>
        </motion.div>
      ) : null}

      <motion.h2
        variants={fadeUp}
        className="mt-5 max-w-3xl text-3xl font-extrabold tracking-tight text-white sm:text-4xl lg:text-[2.75rem] lg:leading-[1.1]"
      >
        {title}{" "}
        {highlight ? (
          <span className="text-gradient-emerald">{highlight}</span>
        ) : null}
      </motion.h2>

      {description ? (
        <motion.p
          variants={fadeUp}
          className="mt-5 max-w-2xl text-base leading-relaxed text-slate-400 sm:text-lg"
        >
          {description}
        </motion.p>
      ) : null}
    </motion.header>
  );
}
