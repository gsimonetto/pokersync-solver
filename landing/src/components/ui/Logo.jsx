import logoUrl from "../../assets/pokersync-logo.svg";

/** Marca oficial (public/pokersync-logo.svg do produto). Monocromática. */
export default function Logo({ className = "h-7 w-auto sm:h-8" }) {
  return (
    <a href="#top" aria-label="PokerSync — página inicial" className="inline-flex">
      <img src={logoUrl} alt="PokerSync" className={className} />
    </a>
  );
}
