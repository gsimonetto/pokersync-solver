import Navbar from "./components/Navbar.jsx";
import Hero from "./components/Hero.jsx";
import EcosystemCycle from "./components/EcosystemCycle.jsx";
import ModulesGrid from "./components/ModulesGrid.jsx";
import TeamMode from "./components/TeamMode.jsx";
import ComparisonTable from "./components/ComparisonTable.jsx";
import FinalCTA from "./components/FinalCTA.jsx";
import Footer from "./components/Footer.jsx";

export default function App() {
  return (
    <div className="relative min-h-screen overflow-x-hidden bg-abyss-900">
      <a
        href="#modulos"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-emerald-500 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-abyss-950"
      >
        Pular para o conteúdo
      </a>

      <Navbar />

      <main>
        <Hero />
        <EcosystemCycle />
        <ModulesGrid />
        <TeamMode />
        <ComparisonTable />
        <FinalCTA />
      </main>

      <Footer />
    </div>
  );
}
