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
  GET  /jobs/{job_id}      -> consulta status (tambem pode ser lido direto
                               do Supabase pela tabela `solver_jobs`, esse
                               endpoint existe só por conveniência/uniformidade)
  POST /hands/compute_cev  -> cEV/ICM de UMA mão jogada (all-in heads-up
                               com as duas mãos conhecidas) — síncrono,
                               <1s, sem treino de CFR (cálculo analítico
                               direto, ver engine/hand_cev.py). Não grava
                               nada no Supabase — o produto decide o que
                               fazer com o resultado.

Autenticação: header `X-API-Key`, comparado contra SOLVER_API_KEY.
"""

import datetime
import os
import uuid
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from jobs.supabase_client import get_client
from jobs.solve_pushfold_batch import run_pushfold_batch
from jobs.solve_rfi_jam_batch import run_rfi_jam_batch
from engine.equity_final import build_final_equity_matrix
from engine.hand_cev import compute_hand_cev, HandCevError

app = FastAPI(title="PokerSync Solver API", version="0.1.0")


def check_api_key(x_api_key: Optional[str] = Header(default=None)):
    expected = os.environ.get("SOLVER_API_KEY")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="API key invalida ou ausente")


class PushFoldJobRequest(BaseModel):
    stacks_bb: list[float]
    other_stacks: list[float]
    payouts: list[float]
    iterations: int = 2000


@app.post("/jobs/pushfold")
def create_pushfold_job(req: PushFoldJobRequest, background_tasks: BackgroundTasks,
                         x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)

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
            equity_matrix, classes, _stats = build_final_equity_matrix()
            run_pushfold_batch(
                job_id=job_id,
                stacks_bb=req.stacks_bb,
                table_context={"other_stacks": req.other_stacks},
                payouts=req.payouts,
                equity_matrix=equity_matrix,
                classes=classes,
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


class RfiJamJobRequest(BaseModel):
    matchups: list[str]
    stacks_bb: list[float]
    other_stacks: list[float]
    payouts: list[float]
    open_size: float = 2.2
    # Lista de tamanhos (ex [2.0, 2.5, 3.0]) -- quando informada com 2+
    # itens, gera o spot no formato multi-tamanho (grava numa linha
    # separada, sufixo "_msize" no spot_id, não mexe no spot de 1
    # tamanho já em produção pro mesmo matchup/stack). Omitir mantém o
    # comportamento de sempre (open_size escalar).
    open_sizes: list[float] | None = None
    iterations: int = 2_500_000
    # Ante de CADA jogador (bb) e quantos assentos pagam ante -- default
    # 0.0/8 mantem o comportamento de sempre (spot sem sufixo _ante, ver
    # jobs/solve_rfi_jam_batch.py). Passar ante_bb>0 gera o spot COM ante
    # (ver engine/rfi_jam.py::ante_pool) sem nunca sobrescrever os spots
    # sem ante ja em producao.
    ante_bb: float = 0.0
    table_size: int = 8


@app.post("/jobs/rfi_jam")
def create_rfi_jam_job(req: RfiJamJobRequest, background_tasks: BackgroundTasks,
                        x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)

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
            equity_matrix, classes, _stats = build_final_equity_matrix()
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
                ante_bb=req.ante_bb,
                table_size=req.table_size,
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
    client = get_client()
    result = client.table("solver_jobs").select("*").eq("id", job_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Job nao encontrado")
    return result.data


class HandCevRequest(BaseModel):
    hero_combo: str  # ex "AhKd" — cartas do hero, mostradas no showdown
    villain_combo: str  # ex "QcQh" — cartas do vilão, mostradas no showdown
    hero_stack_before: float
    villain_stack_before: float
    other_stacks: list[float] = []
    payouts: list[float]
    iterations: int = 5000


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


@app.get("/health")
def health():
    return {"status": "ok"}
