import {
  Target,
  TrendingUp,
  BookOpen,
  Trophy,
  Users,
  LineChart,
  Layers,
} from "lucide-react";

/**
 * Paleta de acento — espelha ACCENT de lib/modules-data.tsx do produto
 * (gsimonetto/pokersync). Não inventar cor aqui: a identidade de cada
 * módulo já está definida lá.
 */
export const ACCENT = {
  green: "#2FB89A",
  blue: "#5AA6E0",
  purple: "#A855F7",
  amber: "#E0B24C",
  pink: "#E0559E",
  cyan: "#22D3EE",
  indigo: "#6366F1",
};

/**
 * Os 7 módulos reais do PokerSync. `title`, `subtitle`, `icon`, `accent` e
 * `href` vêm do produto; `pain`, `value`, `metric` e `cta` são a camada
 * comercial da landing.
 */
export const modules = [
  {
    key: "drill",
    icon: Target,
    title: "Modo Treino",
    subtitle: "Ranges e frequências GTO",
    accent: ACCENT.green,
    href: "/treino",
    pain: "Treinar cenários genéricos, longe do contexto real de jogo.",
    value:
      "Transfira seus leaks do Revisor para sessões de treino interativo em 1 clique.",
    metric: "+35%",
    metricLabel: "de velocidade nos treinos",
    cta: "Treine suas decisões no limite",
  },
  {
    key: "bankroll",
    icon: TrendingUp,
    title: "Gestão de Banca",
    subtitle: "Controle de risco e ROI",
    accent: ACCENT.blue,
    href: "/banca",
    pain: "Controlar lucros e perdas em planilhas manuais e desatualizadas.",
    value:
      "Gestão financeira em tempo real integrada aos seus resultados de sessão.",
    metric: "0",
    metricLabel: "exportações manuais por mês",
    cta: "Domine seu patrimônio no poker",
  },
  {
    key: "revisor",
    icon: BookOpen,
    title: "Revisão de Mãos",
    subtitle: "Análise técnica de jogadas",
    accent: ACCENT.purple,
    href: "/revisor",
    pain: "Demora para encontrar erros e incerteza de como corrigi-los.",
    value:
      "Identificação automática de leaks com conexão direta ao Construtor de Ranges.",
    metric: "8x",
    metricLabel: "mais rápido que revisão manual",
    cta: "Elimine seus leaks hoje",
  },
  {
    key: "ranges",
    icon: Layers,
    title: "Construtor de Ranges",
    subtitle: "Mapeamento estratégico",
    accent: ACCENT.pink,
    href: "/ranges",
    pain: "Tabelas de range estáticas, difíceis de consultar e memorizar.",
    value:
      "Matrizes dinâmicas e interativas que alimentam seus Drills automaticamente.",
    metric: "1.326",
    metricLabel: "combos editáveis por spot",
    cta: "Crie estratégias imbatíveis",
  },
  {
    key: "time",
    icon: Users,
    title: "Meu Time",
    subtitle: "Membros, papéis e convites",
    accent: ACCENT.indigo,
    href: "/time",
    pain: "Caos na gestão de dezenas de jogadores, split de lucros e acompanhamento técnico.",
    value:
      "Painel 360° para donos de time: relatórios de ROI, controle de caixa e performance coletiva.",
    metric: "100+",
    metricLabel: "jogadores por operação",
    cta: "Escale a gestão da sua cavalariça",
  },
  {
    key: "performance",
    icon: LineChart,
    title: "Player Evolution",
    subtitle: "ROI, ABI e tendências de performance",
    accent: ACCENT.cyan,
    href: "/performance",
    pain: "Sensação de estagnação sem saber se está evoluindo no longo prazo.",
    value:
      "Dashboard unificado com taxa de vitória (bb/100), EV, volume e tendências.",
    metric: "bb/100",
    metricLabel: "com curva de EV ajustada",
    cta: "Acompanhe sua evolução técnica",
  },
  {
    key: "hub",
    icon: Trophy,
    title: "Hub de Evolução",
    subtitle: "XP, missões e ranking",
    accent: ACCENT.amber,
    href: "/hub",
    pain: "Estudar sem constância porque nada mede o esforço no dia a dia.",
    value:
      "XP, missões diárias e ranking que transformam disciplina de estudo em progresso visível.",
    metric: "Nível",
    metricLabel: "que sobe a cada sessão de estudo",
    cta: "Suba de nível estudando",
  },
];
