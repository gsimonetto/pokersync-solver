# Instruções para o Claude neste projeto

## Regra obrigatória: validação rigorosa do motor de solver

Sempre que for validar, revisar ou dar sinal verde para qualquer resultado
gerado pelo motor (`engine/multiway_rfi.py`, `engine/rfi_jam.py`, ou
qualquer motor de solver futuro), **não é suficiente checar só**:
- valores extremos (mãos óbvias tipo AA, 72o)
- ausência de NaN/valores fora de [0,1]
- estrutura geral (chaves, formato do dict)

Essas checagens NÃO detectam mãos "travadas" numa decisão errada por
convergência ruim do CFR — que é um problema real e recorrente já
encontrado neste projeto (ver histórico: mãos como A5s, A2s, KQs, QJs
apareceram com frequência de abertura próxima de 0% quando na verdade
"abrir" valia claramente mais que "desistir").

**Antes de dizer que um resultado está pronto para uso ("pode deixar
rodando", "está certinho"), é obrigatório rodar uma checagem de EV
(abrir vs desistir, ou call vs fold) comparando o valor calculado
diretamente (via best-response) com a frequência que o motor realmente
aprendeu. Qualquer mão onde a direção diverge (gap > ~0.3 e o treino
discorda) precisa ser reportada.**

Já existe uma ferramenta pronta pra isso — não escrever script solto de
novo, usar direto:
- `MultiwayRfiSolver.check_full_convergence(avg_strategy=None,
  sample_hands=None, iterations=25, phase2_iterations=40,
  gap_threshold=0.3)` em `engine/multiway_rfi.py` — cobre TODAS as
  decisões do motor (2026-09 v3, ver histórico abaixo), não só o
  abridor: devolve um dict `{"opener_phase1": [...], "other_phase1":
  [...], "phase2": [...]}`, cada lista no formato
  `{hand, gap, trained_freq}` (mais `seat`/`jammer` nas duas últimas
  categorias) com as decisões que ficaram na direção errada.
  - `opener_phase1`: abrir vs desistir do abridor (seat 0).
  - `other_phase1`: fold vs jam de cada seat >= 1 quando a ação chega
    nele em fase 1.
  - `phase2`: call vs fold de qualquer seat (incluindo o abridor)
    respondendo a um all-in de qualquer jammer possível.
  Métodos individuais (`check_opener_convergence`,
  `check_seat_phase1_convergence`, `check_phase2_convergence`) também
  existem separados, se for preciso focar numa categoria só.
- `run_offline_all_positions.py` já chama `check_full_convergence()`
  automaticamente depois de cada treino e salva o resultado (esse dict
  com 3 categorias) em `sanity_flags` dentro do `resultado_*.pkl` — ao
  conferir um arquivo nesse formato, ler esse campo primeiro antes de
  rodar checagem manual do zero. Arquivos `resultado_*.pkl` gerados
  ANTES dessa versão têm `sanity_flags` como lista simples (só
  `opener_phase1`) -- formato antigo, não o dict de 3 categorias.
- Todas essas checagens rodam com `equity_precision_batch=600` por
  padrão -- ver histórico abaixo sobre por que isso é necessário (não
  é só cosmético, era a causa de 40% de falso alarme num resultado
  real antes dessa correção).

Motivo: o usuário odeia retrabalho. Uma validação incompleta que exige
voltar atrás depois (como já aconteceu) é pior do que demorar mais na
validação inicial.

## Histórico: por que a checagem mudou tanto (2026-09)

Auditando um resultado real (CO vs BB 15bb, 4 seats, 5M iterações),
`check_opener_convergence` original apontou 68 de 169 mãos (40%!) como
"na direção errada" -- desproporcional demais pra ser só convergência
lenta. Investigação encontrou dois bugs NA FERRAMENTA DE CHECAGEM, não
no treino:
1. **Vazamento**: julgava a decisão de fase 1 do abridor usando a
   resposta de fase 2 dele MESMO ainda não validada (efeito circular).
   Corrigido fixando a resposta de fase 2 via best-response antes
   (mesma técnica de `compute_exploitability`).
2. **Ruído**: com 3+ adversários, cada reamostragem caía numa
   combinação de mãos quase sempre NOVA, então o cache incremental de
   equity (pensado pra CFR, que revisita a MESMA combinação milhões de
   vezes) nunca acumulava precisão -- cada amostra usava só 150
   simulações brutas, sozinha. Confirmado empiricamente: rodando a
   MESMA mão duas vezes, o gap trocava de sinal. Corrigido pedindo uma
   equity mais precisa por amostra (`equity_precision_batch`) em vez
   de mais reamostragens.

Depois da correção, reconferindo as 68 mãos com amostragem grande
(300-3000 por mão): **68 de 68 eram falso alarme** -- o treino de
produção estava correto, só a ferramenta de checagem que mentia.
Lição: ao investigar um `sanity_flags` suspeito, considerar SEMPRE a
hipótese de bug na própria checagem, não só no motor -- rodar de novo
com mais amostras/seed diferente antes de reportar como bug real.

## Nota sobre `use_cfr_plus`

`MultiwayRfiSolver` tem um parâmetro `use_cfr_plus` (default `True`) que
liga o piso de regret em zero e a média da estratégia ponderada por
iteração (CFR+). Isso é o que roda em produção (mais rápido pra
convergir). Só é desligado no teste de lockstep
(`tests/multiway_rfi.py`), porque o motor heads-up de referência
(`engine/rfi_jam.py`) usa CFR clássico -- os dois só batem EXATAMENTE
se rodarem o mesmo algoritmo. Isso não afeta a validação de EV acima.
