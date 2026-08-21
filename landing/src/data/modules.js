import {
  Target,
  Wallet,
  ScanSearch,
  Users,
  Grid3x3,
  LineChart,
} from "lucide-react";

/**
 * Os 6 pilares do ecossistema PokerSync.
 * `pain` fica no hover do card — a dor é o gancho, o valor é a promessa.
 */
export const modules = [
  {
    id: "drills",
    badge: "Modo Treino",
    title: "Drills que nascem dos seus próprios erros",
    icon: Target,
    accent: "emerald",
    pain: "Treinar cenários genéricos, longe do contexto real de jogo.",
    value:
      "Transfira seus leaks do Revisor para sessões de treino interativo em 1 clique.",
    metric: "+35%",
    metricLabel: "de velocidade nos treinos",
    cta: "Treine suas decisões no limite",
    href: "#treino",
  },
  {
    id: "bankroll",
    badge: "Gestor de Banca",
    title: "Sua banca viva, não uma planilha morta",
    icon: Wallet,
    accent: "indigo",
    pain: "Controlar lucros e perdas em planilhas manuais e desatualizadas.",
    value:
      "Gestão financeira em tempo real integrada aos seus resultados de sessão.",
    metric: "0",
    metricLabel: "exportações manuais por mês",
    cta: "Domine seu patrimônio no poker",
    href: "#banca",
  },
  {
    id: "review",
    badge: "Revisor de Mãos",
    title: "Leaks encontrados antes de custarem caro",
    icon: ScanSearch,
    accent: "emerald",
    pain: "Demora para encontrar erros e incerteza de como corrigi-los.",
    value:
      "Identificação automática de leaks com conexão direta ao Construtor de Ranges.",
    metric: "8x",
    metricLabel: "mais rápido que revisão manual",
    cta: "Elimine seus leaks hoje",
    href: "#revisor",
  },
  {
    id: "team",
    badge: "Modo Time · B2B",
    title: "Cavalariça inteira sob um só painel",
    icon: Users,
    accent: "indigo",
    pain: "Caos na gestão de dezenas de jogadores, split de lucros e acompanhamento técnico.",
    value:
      "Painel 360° para donos de time: relatórios de ROI, controle de caixa e performance coletiva.",
    metric: "100+",
    metricLabel: "jogadores por operação",
    cta: "Escale a gestão da sua cavalariça",
    href: "#times",
  },
  {
    id: "ranges",
    badge: "Construtor de Ranges",
    title: "Matrizes que treinam junto com você",
    icon: Grid3x3,
    accent: "emerald",
    pain: "Tabelas de range estáticas, difíceis de consultar e memorizar.",
    value:
      "Matrizes dinâmicas e interativas que alimentam seus Drills automaticamente.",
    metric: "1.326",
    metricLabel: "combos editáveis por spot",
    cta: "Crie estratégias imbatíveis",
    href: "#ranges",
  },
  {
    id: "evolution",
    badge: "Player Evolution",
    title: "A prova de que você está evoluindo",
    icon: LineChart,
    accent: "indigo",
    pain: "Sensação de estagnação sem saber se está evoluindo no longo prazo.",
    value:
      "Dashboard unificado com taxa de vitória (bb/100), EV, volume e tendências.",
    metric: "bb/100",
    metricLabel: "com curva de EV ajustada",
    cta: "Acompanhe sua evolução técnica",
    href: "#evolution",
  },
];

/** Paletas por acento — evita string dinâmica de classe (Tailwind purge-safe). */
export const accentStyles = {
  emerald: {
    iconWrap:
      "from-emerald-400/25 to-emerald-600/5 border-emerald-500/30 text-emerald-300",
    badge: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
    metric: "text-emerald-400",
    hoverBorder: "group-hover:border-emerald-500/40",
    glow: "group-hover:shadow-glow",
    cta: "text-emerald-400 hover:text-emerald-300",
    ring: "bg-emerald-500/10",
  },
  indigo: {
    iconWrap:
      "from-indigo-400/25 to-indigo-600/5 border-indigo-500/30 text-indigo-300",
    badge: "border-indigo-500/25 bg-indigo-500/10 text-indigo-300",
    metric: "text-indigo-400",
    hoverBorder: "group-hover:border-indigo-500/40",
    glow: "group-hover:shadow-glow-indigo",
    cta: "text-indigo-400 hover:text-indigo-300",
    ring: "bg-indigo-500/10",
  },
};
