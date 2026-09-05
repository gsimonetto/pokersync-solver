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
- `MultiwayRfiSolver.check_opener_convergence(avg_strategy=None,
  sample_hands=None, iterations=25, gap_threshold=0.3)` em
  `engine/multiway_rfi.py` — testa as 169 mãos do abridor (ou uma
  amostra, via `sample_hands`) e devolve as que ficaram na direção
  errada. ~2-3s por mão com iterations=25.
- `run_offline_all_positions.py` já chama isso automaticamente depois
  de cada treino e salva o resultado em `sanity_flags` dentro do
  `resultado_*.pkl` — ao conferir um arquivo nesse formato, ler esse
  campo primeiro antes de rodar checagem manual do zero.
- Essa checagem cobre hoje só a decisão do ABRIDOR (fase 1, seat 0).
  As decisões de fold/jam dos outros seats e as respostas de fase 2
  (call/fold a um all-in) usam o mesmo mecanismo de CFR e podem, em
  tese, sofrer do mesmo problema -- ainda não têm uma checagem
  automática equivalente. Se for validar um resultado a fundo,
  mencionar essa lacuna e considerar estender o método pra cobrir isso
  também.

Motivo: o usuário odeia retrabalho. Uma validação incompleta que exige
voltar atrás depois (como já aconteceu) é pior do que demorar mais na
validação inicial.
