# PokerSync — Landing Page

Landing page oficial de conversão do **PokerSync**: o ecossistema unificado
de alta performance para jogadores e times de poker.

Stack: **React 18 + Vite + Tailwind CSS + Framer Motion + Lucide React**.

## Rodar localmente

```bash
cd landing
npm install
npm run dev      # http://localhost:5173
```

Build de produção:

```bash
npm run build    # gera dist/
npm run preview
```

## Narrativa comercial

A página é construída em cima de um único argumento: **a roda da
fragmentação custa caro**. O jogador paga 5 assinaturas, exporta arquivos
à mão e não consegue ligar teoria (ranges) → prática (drills) → resultado
financeiro (banca/EV). A prova de valor é o *loop fechado*:

```
Revisor de Mãos → Construtor de Ranges → Modo Treino → Banca & Evolution
```

## Estrutura

```
src/
  App.jsx                     Composição das seções
  index.css                   Base do design system (glass, gradientes, scrollbar)
  lib/motion.js               Variantes compartilhadas de Framer Motion
  data/modules.js             Conteúdo dos 6 módulos + paletas de acento
  components/
    Navbar.jsx                Header fixo + drawer mobile
    Hero.jsx                  Headline, CTAs e prova social
    DashboardMockup.jsx       Mock animado do app (KPIs, curva de EV, range)
    EcosystemCycle.jsx        Diagrama interativo do ciclo integrado
    ModulesGrid.jsx           Grid 3x2 dos módulos
    ModuleCard.jsx            Card individual: dor → valor → métrica → CTA
    TeamMode.jsx              Seção B2B (staking / cavalariças)
    ComparisonTable.jsx       5 softwares vs. PokerSync
    FinalCTA.jsx              Fechamento + captura de e-mail
    Footer.jsx                Links institucionais, sociais e aviso legal
    ui/                       Button, Badge, Logo, SectionHeading
```

## Design system aplicado

| Token | Uso |
| --- | --- |
| `abyss-900` (`#090d16`) | Fundo base; `abyss-950` para faixas alternadas |
| `emerald-500` | Ações de conversão, lucro e EV positivo |
| `indigo-500` | Badges, estatísticas e linguagem de "ecossistema" |
| `.glass-panel` | Superfície glassmorphism (`border-white/10` + `backdrop-blur-md`) |
| `.tabular` | Números financeiros com largura fixa (evita "dança" de dígitos) |

Animações: entradas de 0.5–0.7s com easing `[0.22, 1, 0.36, 1]`, stagger
de ~0.09s e `viewport={{ once: true }}` — a página nunca re-anima no
scroll de volta. Todas as animações são desligadas sob
`prefers-reduced-motion: reduce`.

## Pontos de integração

- `FinalCTA.jsx` → `handleSubmit()` está mockado; trocar pelo `POST` real
  de captação de leads.
- Âncoras (`#cadastro`, `#login`, `#modulos`…) apontam para seções da
  própria página; trocar pelas rotas do app quando existirem.
