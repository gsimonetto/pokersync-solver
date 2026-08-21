const base =
  "inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-abyss-900 disabled:opacity-60";

const variants = {
  primary:
    "bg-emerald-500 text-abyss-950 shadow-glow hover:bg-emerald-400 hover:shadow-glow-lg active:scale-[0.98]",
  outline:
    "border border-white/15 bg-white/[0.03] text-slate-100 backdrop-blur-md hover:border-emerald-500/40 hover:bg-emerald-500/[0.08] hover:text-white active:scale-[0.98]",
  ghost: "text-slate-300 hover:text-white",
  indigo:
    "bg-indigo-500 text-white shadow-glow-indigo hover:bg-indigo-400 active:scale-[0.98]",
};

const sizes = {
  sm: "px-4 py-2 text-sm",
  md: "px-5 py-2.5 text-sm",
  lg: "px-7 py-3.5 text-base",
};

/**
 * Botão polimórfico: renderiza `<a>` quando recebe `href`, `<button>` caso contrário.
 * Mantém a hierarquia de conversão (primary = verde neon) consistente na página.
 */
export default function Button({
  as,
  href,
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}) {
  const Component = as || (href ? "a" : "button");
  return (
    <Component
      href={href}
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {children}
    </Component>
  );
}
