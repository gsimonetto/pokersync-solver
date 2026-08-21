# PokerSync — Landing Page

Landing page oficial de conversão do **PokerSync**: o ecossistema unificado
de alta performance para jogadores e times de poker.

Stack: **React 18 + Vite + Tailwind CSS v4 + Framer Motion + Lucide React** —
mesma linguagem visual do produto (`gsimonetto/pokersync`, Next.js 15).

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

## HTML único (sem build)

`pokersync-landing.html` na raiz de `landing/` é a página inteira em um
arquivo só — CSS e JS inline, nenhum servidor necessário. Basta abrir no
navegador ou subir num bucket/CDN.

```bash
npm run build:html   # regenera pokersync-landing.html a partir do src/
```

O bundle sai em formato IIFE (script clássico, não módulo) justamente
para funcionar em `file://`, onde módulos ES são bloqueados por CORS.
A única dependência externa é a fonte Inter via Google Fonts — sem rede,
cai no stack de sistema sem quebrar o layout.

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
    ModulesGrid.jsx           Grid dos 7 módulos reais
    ModuleCard.jsx            Card individual: dor → valor → métrica → CTA
    TeamMode.jsx              Seção B2B (staking / cavalariças)
    ComparisonTable.jsx       5 softwares vs. PokerSync
    FinalCTA.jsx              Fechamento + captura de e-mail
    Footer.jsx                Links institucionais, sociais e aviso legal
    ui/                       Button, Chip, Eyebrow, Logo, Rings, SectionHeading
```

## Identidade visual — fonte da verdade

**Nada de design nasce aqui.** Todos os tokens, cores e padrões vêm do
produto (`gsimonetto/pokersync`). Se a identidade mudar, ela muda lá e é
espelhada aqui.

| O que | De onde veio |
| --- | --- |
| Tokens `@theme` (void/surface/elevated/ink/muted/hairline/positive/negative) | `app/globals.css` |
| Utilitários de acento `.acc-card`, `.acc-glow`, `.acc-fg`, `.acc-bar`, `.tnum`, `glow-breathe` | `app/globals.css` |
| Paleta `ACCENT` e os 7 módulos (título, subtítulo, ícone, cor, rota) | `lib/modules-data.tsx` |
| Logo `pokersync-logo.svg` | `public/` |
| Fonte Space Grotesk | `app/layout.tsx` |
| Card de módulo + `is-active` no toque | `components/module-card.tsx`, `components/module-card-shell.tsx` |
| `Chip` (pill com glow na cor) | `components/chip.tsx` |
| Anéis tracejados, trama de pontos, eyebrow em caixa alta | `components/welcome-hero.tsx`, `app/login/login-form.tsx` |
| Botão primário branco sobre preto | `app/login/login-form.tsx` |
| Matriz de ranges (gradiente fold → call → raise) | `components/ranges/range-grid.tsx` (`cellBackground`) |

### Regras da marca que a landing respeita

1. **Fundo preto puro** (`#000`), superfícies em `#111` e `#1e1e1e`,
   divisórias em branco a 8%.
2. **Ação primária é branca**, nunca colorida — cor viva é identidade de
   módulo, não de botão.
3. **Cada módulo tem um acento próprio** aplicado via `--acc`; a landing
   usa exatamente as cores já atribuídas no produto.
4. **Números sempre com `.tnum`** (largura fixa, evita "dança" de dígitos).

## Pontos de integração

- `FinalCTA.jsx` → `handleSubmit()` está mockado; trocar pelo `POST` real
  de captação de leads.
- Âncoras (`#cadastro`, `#login`, `#modulos`…) apontam para seções da
  própria página; trocar pelas rotas do app quando existirem.
