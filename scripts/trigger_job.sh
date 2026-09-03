#!/usr/bin/env bash
#
# Dispara um job de geracao de spots direto pela API do motor em
# producao (Railway), sem precisar abrir o /docs e clicar em Execute
# manualmente. Le SOLVER_API_URL e SOLVER_API_KEY do ambiente (ou de um
# arquivo .env na raiz do repo, se existir) -- nunca hardcoded aqui, pra
# nao deixar a chave gravada no historico do git.
#
# Uso:
#   ./scripts/trigger_job.sh pushfold [stacks...]
#   ./scripts/trigger_job.sh rfi_jam <matchup> [stacks...]
#
# Exemplos:
#   ./scripts/trigger_job.sh pushfold                  # usa 10 20 30 50 (padrao)
#   ./scripts/trigger_job.sh pushfold 15 25 40 60       # stacks customizados
#   ./scripts/trigger_job.sh rfi_jam sb_vs_bb 15 25 40 60
#
# Depois de disparar, o script fica perguntando o status a cada 5s ate'
# o job terminar (done/error) -- nao precisa ficar voltando no /docs pra
# conferir.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Carrega .env da raiz do repo se existir (mesma convencao do README:
# SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SOLVER_API_KEY). Nao
# sobrescreve variaveis ja exportadas no shell.
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

: "${SOLVER_API_URL:=https://pokersync-solver-production.up.railway.app}"

if [ -z "${SOLVER_API_KEY:-}" ]; then
  echo "Erro: SOLVER_API_KEY nao configurada." >&2
  echo "Exporte a variavel ou crie um .env na raiz do repo com SOLVER_API_KEY=..." >&2
  exit 1
fi

JOB_TYPE="${1:-}"
if [ -z "$JOB_TYPE" ]; then
  echo "Uso: $0 pushfold [stacks...]" >&2
  echo "     $0 rfi_jam <matchup> [stacks...]" >&2
  exit 1
fi
shift

OTHER_STACKS="[40, 25, 18, 12]"
PAYOUTS="[500, 300, 200]"

json_stacks() {
  # Junta os args numericos recebidos num array JSON: 10 20 30 -> [10, 20, 30]
  local IFS=,
  echo "[$*]"
}

case "$JOB_TYPE" in
  pushfold)
    if [ "$#" -eq 0 ]; then STACKS=(10 20 30 50); else STACKS=("$@"); fi
    BODY=$(cat <<EOF
{"stacks_bb": $(json_stacks "${STACKS[@]}"), "other_stacks": $OTHER_STACKS, "payouts": $PAYOUTS}
EOF
)
    ENDPOINT="/jobs/pushfold"
    ;;
  rfi_jam)
    MATCHUP="${1:-}"
    if [ -z "$MATCHUP" ]; then
      echo "Uso: $0 rfi_jam <matchup ex: sb_vs_bb> [stacks...]" >&2
      exit 1
    fi
    shift
    if [ "$#" -eq 0 ]; then STACKS=(15 25 40 60); else STACKS=("$@"); fi
    BODY=$(cat <<EOF
{"matchups": ["$MATCHUP"], "stacks_bb": $(json_stacks "${STACKS[@]}"), "other_stacks": $OTHER_STACKS, "payouts": $PAYOUTS}
EOF
)
    ENDPOINT="/jobs/rfi_jam"
    ;;
  *)
    echo "Tipo de job desconhecido: $JOB_TYPE (use 'pushfold' ou 'rfi_jam')" >&2
    exit 1
    ;;
esac

echo "Disparando $ENDPOINT com:"
echo "$BODY"
echo

RESPONSE=$(curl -sS -X POST "${SOLVER_API_URL}${ENDPOINT}" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${SOLVER_API_KEY}" \
  -d "$BODY")

echo "Resposta: $RESPONSE"

JOB_ID=$(echo "$RESPONSE" | grep -o '"job_id"[^,}]*' | grep -o '"[0-9a-f-]\{36\}"' | tr -d '"')
if [ -z "$JOB_ID" ]; then
  echo "Nao consegui extrair job_id da resposta -- confira o erro acima." >&2
  exit 1
fi

echo
echo "Acompanhando job $JOB_ID..."
while true; do
  sleep 5
  STATUS_JSON=$(curl -sS "${SOLVER_API_URL}/jobs/${JOB_ID}" -H "X-API-Key: ${SOLVER_API_KEY}")
  STATUS=$(echo "$STATUS_JSON" | grep -o '"status":"[a-z]*"' | head -1 | cut -d'"' -f4)
  PROGRESS=$(echo "$STATUS_JSON" | grep -o '"progress":"[^"]*"' | head -1 | cut -d'"' -f4)
  echo "  status=$STATUS progress=${PROGRESS:-N/A}"
  if [ "$STATUS" = "done" ] || [ "$STATUS" = "error" ]; then
    echo
    echo "Resultado final: $STATUS_JSON"
    break
  fi
done
