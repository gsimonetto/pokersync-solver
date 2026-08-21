/** Pílula de destaque usada em eyebrows de seção e tags de módulo. */
export default function Badge({ icon: Icon, children, className = "" }) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border border-indigo-500/25 bg-indigo-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-indigo-300 backdrop-blur-sm ${className}`}
    >
      {Icon ? <Icon className="h-3.5 w-3.5" strokeWidth={2} /> : null}
      {children}
    </span>
  );
}
