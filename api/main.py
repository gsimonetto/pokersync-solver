"""
API mínima do pokersync-solver: dispara/monitora jobs em lote, e agora
também resolve sob demanda o cEV/ICM de uma mão específica (2026-08 —
era a exceção registrada no comentário antigo deste arquivo: "isso fica
pra quando o Hand Replayer precisar" — chegou essa hora).

Endpoints:
  POST /jobs/pushfold      -> dispara um job de geração de spots shove/fold
  POST /jobs/rfi_jam       -> dispara um job de geração de spots RFI/jam
                               (matchups já validados, ver MATCHUPS em
                               jobs/solve_rfi_jam_batch.py)
  POST /jobs/postflop_river -> dispara um job de geração de spots de
                               c-bet no river (só river -- é o único
                               estágio pós-flop com exploitability
                               validada, ver jobs/solve_postflop_batch.py)
  GET  /jobs/{job_id}      -> consulta status (tambem pode ser lido direto
                               do Supabase pela tabela `solver_jobs`, esse
                               endpoint existe só por conveniência/uniformidade)
  POST /hands/compute_cev  -> cEV/ICM de UMA mão jogada (all-in heads-up
                               com as duas mãos conhecidas) — síncrono,
                               <1s, sem treino de CFR (cálculo analítico
                               direto, ver engine/hand_cev.py). Não grava
                               nada no Supabase — o produto decide o que
                               fazer com o resultado.
  POST /hands/compute_cev_multiway -> mesma ideia, mas pra all-in com 3+
                               jogadores e as mãos de TODOS conhecidas
                               (ver engine/hand_cev_multiway.py) —
                               síncrono, ~1-2s (roda ICM a cada iteração
                               de Monte Carlo, mais pesado que o
                               heads-up). Também não grava nada.

Autenticação: header `X-API-Key`, comparado contra SOLVER_API_KEY.
"""

import datetime
import os
import secrets
import uuid
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from jobs.supabase_client import get_client
from jobs.solve_pushfold_batch import run_pushfold_batch
from jobs.solve_rfi_jam_batch import run_rfi_jam_batch
from jobs.solve_postflop_batch import run_postflop_river_batch
from engine.equity_final import get_production_equity_matrix
from engine.hand_cev import compute_hand_cev, HandCevError
from engine.hand_cev_multiway import compute_hand_cev_multiway, HandCevMultiwayError

app = FastAPI(title="PokerSync Solver API", version="0.1.0")


def check_api_key(x_api_key: Optional[str] = Header(default=None)):
    expected = os.environ.get("SOLVER_API_KEY")
    # compare_digest em vez de != -- comparação de string comum vaza, por
    # tempo de execução, quantos caracteres do começo bateram (timing
    # attack). Baixa exploitabilidade aqui (HTTPS via Railway), mas o
    # custo de evitar é zero.
    if not expected or not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="API key invalida ou ausente")


# Mesa de ICM sempre cheia (2026-09-24, pedido do usuario): 8 ou 9
# jogadores = os 2 do spot + 6 ou 7 em other_stacks. Com menos gente na
# mesa o ICM sai bem diferente (cada eliminacao pesa mais), entao uma
# lista curta por engano gerava um spot errado sem avisar ninguem.
ICM_TABLE_SIZES = (8, 9)


def _check_icm_table_size(use_icm: bool, other_stacks: list[float]):
    if not use_icm:
        return
    n = len(other_stacks) + 2
    if n not in ICM_TABLE_SIZES:
        raise HTTPException(
            status_code=422,
            detail=f"other_stacks tem {len(other_stacks)} stacks -> mesa de {n} jogadores; "
                   f"com ICM a mesa precisa ter 8 ou 9 (mande 6 ou 7 stacks em other_stacks)",
        )
    if any(s <= 0 for s in other_stacks):
        raise HTTPException(status_code=422, detail="other_stacks precisa ter so' valores positivos")


class PushFoldJobRequest(BaseModel):
    stacks_bb: list[float]
    other_stacks: list[float]
    # Obrigatorio so' quando use_icm=True (padrao) -- em chipEV puro
    # (use_icm=False) nao entra na conta, pode mandar [].
    payouts: list[float] = []
    # Limite generoso (100x o default) so' pra impedir alguem com a chave
    # de API pedir um numero absurdo de iteracoes e prender o processo/
    # gerar custo de compute sem fim -- nenhum job de producao real chega
    # perto disso.
    iterations: int = Field(default=2000, gt=0, le=200_000)
    # True (padrao, preserva todo spot ja em producao): $ICM -- considera
    # a estrutura de premiacao do torneio. False: chipEV puro (cash game,
    # ou torneio bem no inicio, longe de bolha) -- payouts fica ignorado.
    # Grava um spot SEPARADO (sufixo "_chipev" no spot_id), nunca mexe no
    # spot ICM existente pro mesmo stack.
    use_icm: bool = True


@app.post("/jobs/pushfold")
def create_pushfold_job(req: PushFoldJobRequest, background_tasks: BackgroundTasks,
                         x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    if req.use_icm and not req.payouts:
        raise HTTPException(status_code=422, detail="payouts vazio -- obrigatorio quando use_icm=True (ou mande use_icm=false pra chipEV puro)")
    _check_icm_table_size(req.use_icm, req.other_stacks)

    job_id = str(uuid.uuid4())
    client = get_client()
    client.table("solver_jobs").insert({
        "id": job_id,
        "job_type": "pushfold_icm_batch",
        "status": "running",
        "params": req.model_dump(),
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()

    def _run():
        try:
            equity_matrix, classes = get_production_equity_matrix()
            run_pushfold_batch(
                job_id=job_id,
                stacks_bb=req.stacks_bb,
                table_context={"other_stacks": req.other_stacks},
                payouts=req.payouts,
                equity_matrix=equity_matrix,
                classes=classes,
                iterations=req.iterations,
                use_icm=req.use_icm,
            )
            client.table("solver_jobs").update({
                "status": "done",
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()
        except Exception as e:  # noqa: BLE001
            client.table("solver_jobs").update({
                "status": "error",
                "error": str(e),
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "running"}


class RfiJamJobRequest(BaseModel):
    matchups: list[str]
    stacks_bb: list[float]
    other_stacks: list[float]
    # Obrigatorio so' quando use_icm=True (padrao) -- em chipEV puro
    # (use_icm=False) nao entra na conta, pode mandar [].
    payouts: list[float] = []
    open_size: float = 2.2
    # Lista de tamanhos (ex [2.0, 2.5, 3.0]) -- quando informada com 2+
    # itens, gera o spot no formato multi-tamanho (grava numa linha
    # separada, sufixo "_msize" no spot_id, não mexe no spot de 1
    # tamanho já em produção pro mesmo matchup/stack). Omitir mantém o
    # comportamento de sempre (open_size escalar).
    open_sizes: list[float] | None = None
    # Default de producao ja e' 2.5M -- limite com folga de 4x, so' pra
    # barrar um valor absurdo vindo de um cliente com a chave.
    iterations: int = Field(default=2_500_000, gt=0, le=10_000_000)
    # True (padrao, preserva todo spot ja em producao): $ICM -- considera
    # a estrutura de premiacao do torneio. False: chipEV puro (cash game,
    # ou torneio bem no inicio, longe de bolha) -- payouts fica ignorado.
    # Grava um spot SEPARADO (sufixo "_chipev" no spot_id), nunca mexe no
    # spot ICM existente pro mesmo matchup/stack.
    use_icm: bool = True


@app.post("/jobs/rfi_jam")
def create_rfi_jam_job(req: RfiJamJobRequest, background_tasks: BackgroundTasks,
                        x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    if req.use_icm and not req.payouts:
        raise HTTPException(status_code=422, detail="payouts vazio -- obrigatorio quando use_icm=True (ou mande use_icm=false pra chipEV puro)")
    _check_icm_table_size(req.use_icm, req.other_stacks)

    job_id = str(uuid.uuid4())
    client = get_client()
    client.table("solver_jobs").insert({
        "id": job_id,
        "job_type": "rfi_jam_icm_batch",
        "status": "running",
        "params": req.model_dump(),
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()

    def _run():
        try:
            equity_matrix, classes = get_production_equity_matrix()
            run_rfi_jam_batch(
                job_id=job_id,
                matchups=req.matchups,
                stacks_bb=req.stacks_bb,
                other_stacks=req.other_stacks,
                payouts=req.payouts,
                equity_matrix=equity_matrix,
                classes=classes,
                open_size=req.open_size,
                open_sizes=req.open_sizes,
                iterations=req.iterations,
                use_icm=req.use_icm,
            )
            client.table("solver_jobs").update({
                "status": "done",
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()
        except Exception as e:  # noqa: BLE001
            client.table("solver_jobs").update({
                "status": "error",
                "error": str(e),
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "running"}


class PostflopRiverSpot(BaseModel):
    label: str
    board: str  # ex "Ah Kd 7s 2c 9h" -- sempre 5 cartas (river), ver docstring do job
    range_oop: dict[str, float]
    range_ip: dict[str, float]
    pot: float
    stack_oop: float
    stack_ip: float
    bet_sizes: list[float] = [0.33, 0.75, 1.5]


class PostflopRiverJobRequest(BaseModel):
    # Limite de spots por request: cada spot roda seu proprio treino de
    # solver -- sem isso, uma lista gigante * iterations altas vira um
    # jeito facil de prender o worker por muito tempo.
    spots: list[PostflopRiverSpot] = Field(..., min_length=1, max_length=20)
    iterations: int = Field(default=30_000, gt=0, le=500_000)


@app.post("/jobs/postflop_river")
def create_postflop_river_job(req: PostflopRiverJobRequest, background_tasks: BackgroundTasks,
                               x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)

    job_id = str(uuid.uuid4())
    client = get_client()
    client.table("solver_jobs").insert({
        "id": job_id,
        "job_type": "postflop_river_batch",
        "status": "running",
        "params": req.model_dump(),
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()

    def _run():
        try:
            run_postflop_river_batch(
                job_id=job_id,
                spots=[s.model_dump() for s in req.spots],
                iterations=req.iterations,
            )
            client.table("solver_jobs").update({
                "status": "done",
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()
        except Exception as e:  # noqa: BLE001
            client.table("solver_jobs").update({
                "status": "error",
                "error": str(e),
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }).eq("id", job_id).execute()

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "running"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    # .limit(1) em vez de .single(): com .single(), um id inexistente faz o
    # PostgREST responder erro (0 linhas) e a biblioteca levanta excecao --
    # virava erro 500 em vez do 404 abaixo. Id que nem e' UUID tambem vira
    # 404 direto (o banco rejeitaria a comparacao com a coluna uuid).
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job nao encontrado")
    client = get_client()
    result = client.table("solver_jobs").select("*").eq("id", job_id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Job nao encontrado")
    return result.data[0]


class HandCevRequest(BaseModel):
    hero_combo: str  # ex "AhKd" — cartas do hero, mostradas no showdown
    villain_combo: str  # ex "QcQh" — cartas do vilão, mostradas no showdown
    hero_stack_before: float
    villain_stack_before: float
    other_stacks: list[float] = []
    payouts: list[float]
    # Sincrono (a resposta HTTP so' volta quando termina) -- limite mais
    # apertado que os jobs em background, pra nunca segurar a requisicao
    # por tempo demais.
    iterations: int = Field(default=5000, gt=0, le=50_000)


@app.post("/hands/compute_cev")
def compute_cev(req: HandCevRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    try:
        return compute_hand_cev(
            hero_combo=req.hero_combo,
            villain_combo=req.villain_combo,
            hero_stack_before=req.hero_stack_before,
            villain_stack_before=req.villain_stack_before,
            other_stacks=req.other_stacks,
            hero_seat_idx=0,
            villain_seat_idx=1,
            payouts=req.payouts,
            iterations=req.iterations,
        )
    except HandCevError as e:
        raise HTTPException(status_code=422, detail=str(e))


class HandCevMultiwayRequest(BaseModel):
    combos: list[str]  # ex ["AhAd", "KsKc", "QdQc"] -- cartas de CADA jogador all-in, mostradas no showdown
    stacks_before: list[float]  # mesma ordem de `combos`
    hero_idx: int  # posicao do heroi dentro de combos/stacks_before
    other_stacks: list[float] = []
    payouts: list[float]
    # Sincrono e mais pesado por iteracao que o heads-up (roda ICM a cada
    # volta) -- limite proporcionalmente mais baixo.
    iterations: int = Field(default=1500, gt=0, le=20_000)


@app.post("/hands/compute_cev_multiway")
def compute_cev_multiway(req: HandCevMultiwayRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    try:
        return compute_hand_cev_multiway(
            combos=req.combos,
            stacks_before=req.stacks_before,
            other_stacks=req.other_stacks,
            hero_idx=req.hero_idx,
            payouts=req.payouts,
            iterations=req.iterations,
        )
    except HandCevMultiwayError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok"}
