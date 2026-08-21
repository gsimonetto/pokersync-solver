/**
 * Eyebrow de seção — mesmo tratamento do "Bem-vindo de volta" do
 * WelcomeHero do produto: caixa alta, tracking largo, texto muted.
 */
export default function Eyebrow({ children, className = "" }) {
  return (
    <span
      className={`text-[11px] font-semibold uppercase tracking-[0.28em] text-muted ${className}`}
    >
      {children}
    </span>
  );
}
