"""
Conexão com o Supabase do PokerSync — mesmo projeto (olgziujndtlvxegcnaoq),
usado pra: (1) ler config de spots a resolver, (2) escrever o resultado
final em `drills`, (3) gravar status de jobs em `solver_jobs`.

Usa a service role key (não a anon key) porque isso roda server-side,
nunca exposto ao navegador.
"""

import os
from supabase import create_client, Client

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        _client = create_client(url, key)
    return _client
