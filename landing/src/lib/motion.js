/**
 * Variantes compartilhadas de Framer Motion.
 * Centralizadas para manter o ritmo de animação idêntico em toda a página:
 * entradas curtas (0.5–0.7s), easing suave e stagger previsível.
 */

export const EASE = [0.22, 1, 0.36, 1];

export const viewportOnce = { once: true, amount: 0.25 };

export const fadeUp = {
  hidden: { opacity: 0, y: 28 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: EASE },
  },
};

export const fadeIn = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.7, ease: EASE } },
};

export const fadeLeft = {
  hidden: { opacity: 0, x: -32 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.6, ease: EASE } },
};

export const fadeRight = {
  hidden: { opacity: 0, x: 32 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.6, ease: EASE } },
};

export const scaleIn = {
  hidden: { opacity: 0, scale: 0.94 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.7, ease: EASE },
  },
};

/** Container com stagger — use junto de `fadeUp` nos filhos. */
export const staggerContainer = (stagger = 0.09, delay = 0) => ({
  hidden: {},
  visible: {
    transition: { staggerChildren: stagger, delayChildren: delay },
  },
});
