/**
 * Anéis decorativos tracejados — portado de AnelDecorativo
 * (components/welcome-hero.tsx). Assinatura visual do produto.
 */
function Ring({ size, className = "" }) {
  return (
    <span
      className={`absolute rounded-full border border-dashed border-white/15 ${className}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <span className="absolute inset-2 rounded-full border border-white/[0.06] bg-gradient-to-br from-white/[0.05] to-transparent" />
    </span>
  );
}

export default function Rings({ className = "" }) {
  return (
    <div
      className={`pointer-events-none absolute inset-y-0 right-0 hidden w-1/2 sm:block ${className}`}
      aria-hidden="true"
    >
      <Ring size={190} className="right-6 top-1/2 -translate-y-1/2 opacity-70" />
      <Ring size={130} className="right-40 top-6 opacity-60" />
      <Ring size={96} className="-bottom-6 right-24 opacity-50" />
      <Ring size={64} className="right-2 top-8 opacity-40" />
    </div>
  );
}
