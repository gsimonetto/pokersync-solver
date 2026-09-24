"""
Testes dos endpoints HTTP da API (api/main.py), sem Supabase de verdade:
o cliente do banco é trocado por um falso em memória. Cobre os erros
achados na auditoria de 2026-09-24 que viravam "erro 500" pro produto:

- combo mal formado / carta repetida em /hands/compute_cev(_multiway):
  agora 422 com mensagem clara;
- all-in de 3 jogadores com 2 eliminados em /hands/compute_cev_multiway
  (ICM dividia por zero): agora 200;
- GET /jobs/{id} de um job que não existe: agora 404 (antes o .single()
  do supabase levantava exceção -> 500).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SOLVER_API_KEY"] = "chave-de-teste"

from fastapi.testclient import TestClient  # noqa: E402

import api.main as api_main  # noqa: E402

HEADERS = {"X-API-Key": "chave-de-teste"}


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        return _FakeQuery([r for r in self._rows if r.get(column) == value])

    def limit(self, n):
        return _FakeQuery(self._rows[:n])

    def execute(self):
        return type("Resp", (), {"data": self._rows})()


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _FakeQuery(self._rows)


def _client():
    return TestClient(api_main.app)


def test_chave_obrigatoria():
    body = {"hero_combo": "AhAd", "villain_combo": "KsKc", "hero_stack_before": 3000,
            "villain_stack_before": 3000, "payouts": [500, 300, 200], "iterations": 100}
    r = _client().post("/hands/compute_cev", json=body)
    assert r.status_code == 401, r.text
    r = _client().post("/hands/compute_cev", json=body, headers={"X-API-Key": "errada"})
    assert r.status_code == 401, r.text


def test_compute_cev_ok_e_combo_invalido():
    body = {"hero_combo": "AhAd", "villain_combo": "KsKc", "hero_stack_before": 3000,
            "villain_stack_before": 3000, "other_stacks": [8000, 5000], "payouts": [500, 300, 200],
            "iterations": 2000}
    r = _client().post("/hands/compute_cev", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert 75 < r.json()["hero_equity_pct"] < 90
    for bad in ("ahad", "AhA", "AhAh"):
        r = _client().post("/hands/compute_cev", json={**body, "hero_combo": bad}, headers=HEADERS)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    r = _client().post("/hands/compute_cev", json={**body, "villain_combo": "AhKc"}, headers=HEADERS)
    assert r.status_code == 422, r.text  # carta repetida entre as duas mãos


def test_compute_cev_multiway_dois_eliminados():
    body = {"combos": ["AhAd", "KsKc", "QdQc"], "stacks_before": [2000, 2000, 2000], "hero_idx": 0,
            "other_stacks": [5000], "payouts": [500, 300, 200], "iterations": 500}
    r = _client().post("/hands/compute_cev_multiway", json=body, headers=HEADERS)
    assert r.status_code == 200, r.text
    r = _client().post("/hands/compute_cev_multiway", json={**body, "combos": ["AhAd", "KsK", "QdQc"]},
                       headers=HEADERS)
    assert r.status_code == 422, r.text


def test_get_job_inexistente_da_404():
    job_id = "11111111-2222-3333-4444-555555555555"
    original = api_main.get_client
    api_main.get_client = lambda: _FakeClient([{"id": job_id, "status": "done"}])
    try:
        r = _client().get(f"/jobs/{job_id}", headers=HEADERS)
        assert r.status_code == 200 and r.json()["status"] == "done", r.text
        r = _client().get("/jobs/99999999-2222-3333-4444-555555555555", headers=HEADERS)
        assert r.status_code == 404, r.text
        r = _client().get("/jobs/nao-e-um-uuid", headers=HEADERS)
        assert r.status_code == 404, r.text
    finally:
        api_main.get_client = original


def test_health():
    assert _client().get("/health").json() == {"status": "ok"}


if __name__ == "__main__":
    test_chave_obrigatoria()
    print("  OK -- sem X-API-Key: 401")
    test_compute_cev_ok_e_combo_invalido()
    print("  OK -- /hands/compute_cev: 200 no caso normal, 422 pra combo invalido/carta repetida")
    test_compute_cev_multiway_dois_eliminados()
    print("  OK -- /hands/compute_cev_multiway: 2 eliminados na mesma mao da 200 (antes 500)")
    test_get_job_inexistente_da_404()
    print("  OK -- GET /jobs/{id}: 200 quando existe, 404 quando nao existe (antes 500)")
    test_health()
    print("  OK -- /health")
    print("Todos os testes de api_endpoints passaram.")
