import { Spade } from "lucide-react";

/** Marca PokerSync: ícone com halo emerald + wordmark em gradiente. */
export default function Logo({ className = "" }) {
  return (
    <a
      href="#top"
      aria-label="PokerSync — página inicial"
      className={`group inline-flex items-center gap-2.5 ${className}`}
    >
      <span className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/30 bg-gradient-to-br from-emerald-400/25 to-emerald-600/5 shadow-glow transition-transform duration-300 group-hover:scale-105">
        <span className="absolute inset-0 rounded-xl bg-emerald-500/20 blur-lg" aria-hidden="true" />
        <Spade className="relative h-[18px] w-[18px] text-emerald-300" strokeWidth={2.2} />
      </span>
      <span className="text-lg font-extrabold tracking-tight text-white">
        Poker<span className="text-gradient-emerald">Sync</span>
      </span>
    </a>
  );
}
