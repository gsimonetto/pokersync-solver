const base =
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition-all cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/70 focus-visible:ring-offset-2 focus-visible:ring-offset-void disabled:opacity-50 disabled:cursor-not-allowed";

/**
 * Hierarquia de ação do produto: a ação primária é BRANCA sobre preto
 * (mesmo botão da tela de login). Cor viva nunca é usada em CTA — ela é
 * reservada para o acento de módulo.
 */
const variants = {
  primary: "bg-ink text-void shadow-lg shadow-black/40 hover:bg-white/90",
  outline:
    "border border-hairline bg-surface text-ink hover:border-white/20 hover:bg-elevated",
  ghost: "text-muted hover:text-ink",
};

const sizes = {
  sm: "px-4 py-2 text-sm",
  md: "px-4 py-2.5 text-sm",
  lg: "px-6 py-3 text-[15px]",
};

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
