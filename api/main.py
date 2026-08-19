"""
API mínima do pokersync-solver: só o suficiente pra disparar e
monitorar jobs em lote (decisão registrada: sem resolução sob demanda
ainda, isso fica pra quando o Hand Replayer precisar).

Endpoints:
  POST /jobs/pushfold   -> dispara um job de geração de spots shove/fold
  GET  /jobs/{job_id}   -> consulta status (tambem pode ser lido direto
                            do Supabase pela tabela `solver_jobs`, esse
                            endpoint existe só por conveniência/uniformidade)

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
from engine.equity_final import build_final_equity_matrix

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


@app.get("/jobs/{job_id}")
def get_job(job_id: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    client = get_client()
    result = client.table("solver_jobs").select("*").eq("id", job_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Job nao encontrado")
    return result.data


@app.get("/health")
def health():
    return {"status": "ok"}
