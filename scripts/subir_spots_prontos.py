"""
Sobe pro Supabase (tabela drills) os spots heads-up ja gerados e conferidos
em spots_prontos/*.json (2026-09-25: SB vs BB e BTN vs BB, RFI/jam e
push/fold, mesa de 8, remocao de cartas, matriz de equity precisa).

Uso (na pasta do projeto, com SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no .env):
    python scripts/subir_spots_prontos.py
"""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

faltam = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not os.environ.get(k)]
if faltam:
    sys.exit(f"ERRO: faltam {', '.join(faltam)} no .env -- nada foi enviado.")

from jobs.supabase_client import get_client  # noqa: E402

rows = []
for f in sorted((BASE / "spots_prontos").glob("*.json")):
    rows += json.loads(f.read_text())
if not rows:
    sys.exit("Nenhum spot em spots_prontos/.")
get_client().table("drills").upsert(rows, on_conflict="spot_id").execute()
print(f"OK -- {len(rows)} spots enviados.")
