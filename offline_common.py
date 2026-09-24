"""
Rotinas compartilhadas pelos scripts de treino offline
(run_offline_all_positions.py, run_offline_multiway.py) -- tudo que
existe pra esses scripts NÃO quebrarem no seu PC depois de horas/dias
rodando:

- Checkpoint gravado de forma ATÔMICA (arquivo temporário + troca no
  final). Antes o arquivo era sobrescrito direto: se o PC desligasse ou o
  terminal fosse fechado no meio da gravação, o checkpoint ficava pela
  metade e a próxima execução quebrava ao abrir (EOFError /
  UnpicklingError), perdendo tudo. Agora sempre sobra uma versão inteira
  (a nova ou a anterior, guardada como .bak).
- Checkpoint com VERSÃO do motor + config. Antes gravava o objeto Python
  inteiro; checkpoint de uma versão anterior do código quebrava ao
  retomar (ex: AttributeError 'use_cfr_plus', ValueError no cache de
  equity) -- ou pior, retomava misturando dois algoritmos diferentes na
  mesma média. Agora um checkpoint incompatível é detectado, renomeado
  (nunca apagado) e o treino recomeça do zero com um aviso claro.
- Checagem da versão do Python com mensagem clara (o código usa sintaxe
  que exige 3.10+).
"""

import os
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

MIN_PYTHON = (3, 10)
CHECKPOINT_FORMAT = 2


def check_python_version():
    if sys.version_info < MIN_PYTHON:
        sys.exit(
            f"ERRO: este projeto precisa de Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou mais novo "
            f"(você está usando {sys.version.split()[0]}). Instale um Python mais novo em "
            f"https://www.python.org/downloads/ e recrie o ambiente (.venv)."
        )


def _replace_with_retry(src: Path, dst: Path, attempts: int = 10):
    """os.replace com novas tentativas -- no Windows, antivírus/indexador
    às vezes segura o arquivo por um instante (PermissionError)."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.5 * (i + 1))


def atomic_pickle_dump(obj, path: Path, keep_backup: bool = False):
    """Grava `obj` em `path` sem nunca deixar um arquivo pela metade:
    escreve num .tmp, força ir pro disco, e só então troca pelo definitivo.
    keep_backup: a versão anterior vira `<nome>.bak` (rede de segurança
    extra pra checkpoint)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    if keep_backup and path.exists():
        _replace_with_retry(path, path.with_name(path.name + ".bak"))
    _replace_with_retry(tmp, path)


def move_aside(path: Path, reason: str) -> Path:
    """Renomeia (NUNCA apaga) um arquivo que não dá pra usar -- ex:
    checkpoint_X.pkl -> checkpoint_X.pkl.incompativel-20260924-0310."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.{reason}-{stamp}")
    _replace_with_retry(path, target)
    return target


def save_checkpoint(path: Path, solver, config: dict, done_iterations: int, engine_version: str):
    atomic_pickle_dump({
        "format": CHECKPOINT_FORMAT,
        "engine_version": engine_version,
        "config": config,
        "done_iterations": done_iterations,
        "solver_state": solver.export_state(),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }, path, keep_backup=True)


def _checkpoint_problem(state, config: dict, engine_version: str):
    if not isinstance(state, dict) or state.get("format") != CHECKPOINT_FORMAT:
        return "formato antigo (gravado por uma versão anterior do script)"
    if state.get("engine_version") != engine_version:
        return (f"gravado pela versão {state.get('engine_version')!r} do motor "
                f"(a atual é {engine_version!r}, com correções que mudam o resultado)")
    if state.get("config") != config:
        return "gravado com outra configuração (stacks/payouts/seats diferentes)"
    return None


def load_checkpoint(path: Path, config: dict, engine_version: str, make_solver, log=print):
    """Tenta retomar o treino de `path` (ou do .bak, se o principal estiver
    estragado). Devolve (solver, iterações_feitas) ou None se não houver
    checkpoint aproveitável. Checkpoint estragado/incompatível é
    renomeado (nunca apagado), com aviso explicando o porquê."""
    path = Path(path)
    for candidate in (path, path.with_name(path.name + ".bak")):
        if not candidate.exists():
            continue
        try:
            with open(candidate, "rb") as f:
                state = pickle.load(f)
        except Exception as e:  # noqa: BLE001 -- qualquer falha de leitura = arquivo inutilizável
            moved = move_aside(candidate, "corrompido")
            log(f"  AVISO: {candidate.name} não pôde ser lido ({type(e).__name__}: {e}). "
                f"Renomeado para {moved.name}.")
            continue
        problem = _checkpoint_problem(state, config, engine_version)
        if problem:
            moved = move_aside(candidate, "incompativel")
            log(f"  AVISO: {candidate.name} não pode ser retomado -- {problem}. "
                f"Renomeado para {moved.name}; este treino recomeça do zero.")
            continue
        solver = make_solver()
        try:
            solver.import_state(state["solver_state"])
        except Exception as e:  # noqa: BLE001
            moved = move_aside(candidate, "incompativel")
            log(f"  AVISO: {candidate.name} tem dados que não batem com o motor atual ({e}). "
                f"Renomeado para {moved.name}; este treino recomeça do zero.")
            continue
        if candidate != path:
            log(f"  (usando a cópia de segurança {candidate.name})")
        return solver, int(state["done_iterations"])
    return None


def load_result(path: Path, engine_version: str):
    """Lê um resultado_*.pkl. Devolve (dados, problema): `problema` é None
    se o arquivo é da versão atual do motor, ou um texto explicando por
    que não é (arquivo antigo/ilegível)."""
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:  # noqa: BLE001
        return None, f"arquivo ilegível ({type(e).__name__}: {e})"
    if not isinstance(data, dict) or "strategy" not in data:
        return None, "formato desconhecido"
    version = data.get("engine_version")
    if version != engine_version:
        return data, (f"gerado pela versão {version!r} do motor (a atual é {engine_version!r}) "
                      f"-- antes das correções de 2026-09-24")
    return data, None


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}min"
    return f"{minutes}min"


def train_and_evaluate(label: str, config: dict, total_iterations: int, out_dir: Path, make_solver,
                       engine_version: str, stop, chunk=None, checkpoint_minutes: float = 10.0,
                       final_evaluation: bool = True):
    """Treina (retomando checkpoint se houver) até `total_iterations`,
    depois roda a avaliação final OBRIGATÓRIA (exploitability por seat +
    checagem de convergência de todas as decisões -- ver CLAUDE.md) e
    grava resultado_<label>.pkl. Devolve "done", "skipped" ou "stopped".

    Checkpoint por TEMPO (a cada `checkpoint_minutes`), não por número
    fixo de iterações: o custo por iteração varia 30x entre CO (4 seats) e
    UTG (8 seats), e o que importa é o quanto se perde se o PC desligar
    (no máximo ~10 minutos de treino)."""
    out_dir = Path(out_dir)
    result_path = out_dir / f"resultado_{label}.pkl"
    checkpoint_path = out_dir / f"checkpoint_{label}.pkl"

    if result_path.exists():
        _data, problem = load_result(result_path, engine_version)
        if problem is None:
            print(f"[{label}] já tem resultado final da versão atual ({result_path.name}) -- pulando.")
            return "skipped"
        moved = move_aside(result_path, "versao-antiga")
        print(f"[{label}] o resultado existente não serve mais: {problem}. "
              f"Guardei como {moved.name} (não apaguei) e vou refazer com o motor corrigido.")

    loaded = load_checkpoint(checkpoint_path, config, engine_version, make_solver)
    if loaded is not None:
        solver, done = loaded
        print(f"[{label}] retomando checkpoint: {done:,}/{total_iterations:,} iterações já feitas.")
    else:
        solver = make_solver()
        done = 0
        print(f"[{label}] começando do zero ({solver.n_seats} seats: {', '.join(solver.seat_names)}).")

    if chunk is None:
        # bloco de ~5s em qualquer posição (o custo por iteração dobra a cada
        # seat a mais): é o tempo máximo de espera depois de um Ctrl+C. Fixo
        # por número de seats (não pelo relógio) pra retomar de um checkpoint
        # continuar reproduzível.
        chunk = max(100, 2_000 >> max(0, solver.n_seats - 4))

    t_start = time.time()
    done_at_start = done
    last_save = time.time()
    while done < total_iterations:
        if stop.requested:
            save_checkpoint(checkpoint_path, solver, config, done, engine_version)
            print(f"[{label}] parado a pedido em {done:,} iterações -- checkpoint salvo. "
                  f"Rode o script de novo pra continuar daqui.")
            return "stopped"
        batch = min(chunk, total_iterations - done)
        # seed depende só de `done`: retomar de um checkpoint dá exatamente
        # o mesmo treino que rodar direto, sem interrupção.
        solver.train(iterations=batch, seed=done + 1, start_t=done + 1)
        done += batch
        if time.time() - last_save >= checkpoint_minutes * 60 or done >= total_iterations:
            save_checkpoint(checkpoint_path, solver, config, done, engine_version)
            last_save = time.time()
            elapsed = time.time() - t_start
            rate = (done - done_at_start) / elapsed if elapsed > 0 else 0.0
            eta = (total_iterations - done) / rate if rate > 0 else 0.0
            print(f"  [{label}] {100 * done / total_iterations:5.1f}%  {done:,}/{total_iterations:,}  "
                  f"{rate:,.0f} it/s  falta ~{format_duration(eta)}  (checkpoint salvo)", flush=True)

    if stop.requested:  # Ctrl+C durante o último bloco: o checkpoint final já foi salvo acima
        print(f"[{label}] parado a pedido com o treino completo -- a avaliação final roda na próxima execução.")
        return "stopped"
    if not final_evaluation:
        return "done"

    print(f"  [{label}] treino concluído. Avaliação final (obrigatória, ver CLAUDE.md) -- pode levar "
          f"de minutos a horas conforme o número de seats. Se parar agora (Ctrl+C), o treino continua "
          f"salvo e só esta etapa recomeça na próxima execução.", flush=True)
    stop.immediate = True  # treino já salvo: Ctrl+C aqui sai na hora
    strat = solver.average_strategy()

    t0 = time.time()
    print(f"  [{label}] 1/2 exploitability (melhor resposta de cada seat)...", flush=True)
    br_by_seat = solver.compute_exploitability(strat)
    exploitability = sum(br_by_seat.values())
    t_expl = time.time() - t0
    print(f"  [{label}]     feito em {format_duration(t_expl)}: "
          + ", ".join(f"{solver.seat_names[s]}={v:.3f}" for s, v in br_by_seat.items()), flush=True)

    t0 = time.time()
    print(f"  [{label}] 2/2 checagem de convergência (todas as decisões, todas as 169 mãos)...", flush=True)
    sanity_flags = solver.check_full_convergence(
        strat, progress=lambda msg: print(f"      - {msg}", flush=True)
    )
    t_check = time.time() - t0
    summary = solver.last_check_summary or {}
    total_flags = sum(len(v) for v in sanity_flags.values())
    print(f"  [{label}]     feito em {format_duration(t_check)}: {summary.get('checked', 0)} decisões "
          f"checadas, {total_flags} na direção errada, {summary.get('inconclusive', 0)} inconclusivas "
          f"(diferença dentro do ruído), {summary.get('insufficient_data', 0)} sem dados suficientes.")
    for category, items in sanity_flags.items():
        for f_ in sorted(items, key=lambda x: -abs(x["gap"])):
            who = ""
            if "seat" in f_:
                who = f" {solver.seat_names[f_['seat']]}"
                if "jammer" in f_:
                    who += f" vs jam de {solver.seat_names[f_['jammer']]}"
            print(f"      ATENÇÃO [{category}]{who} {f_['hand']}: gap={f_['gap']:+.3f} "
                  f"(±{f_['se']:.3f}, {f_['n']} mesas)  freq_treinada={f_['trained_freq']:.4f}")

    atomic_pickle_dump({
        "engine_version": engine_version,
        "config": config,
        "strategy": strat,
        "iterations": done,
        "exploitability": exploitability,
        "best_response_by_seat": br_by_seat,
        "sanity_flags": sanity_flags,
        "sanity_summary": summary,
        "timings_seconds": {"exploitability": t_expl, "convergence_check": t_check},
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }, result_path)
    for leftover in (checkpoint_path, checkpoint_path.with_name(checkpoint_path.name + ".bak")):
        leftover.unlink(missing_ok=True)
    stop.immediate = False
    print(f"[{label}] CONCLUÍDO -- exploitability={exploitability:.3f}, {total_flags} decisão(ões) "
          f"suspeita(s) -- salvo em {result_path.name}\n", flush=True)
    return "done"


class GracefulStop:
    """Ctrl+C vira um pedido de parada: o treino termina o bloco atual
    (alguns segundos), grava o checkpoint e sai limpo. Um segundo Ctrl+C
    força a saída imediata (perde só o que foi feito desde o último
    checkpoint). Durante a avaliação final (`immediate=True`) o treino já
    está salvo, então um Ctrl+C sai na hora.

    Ao sair do bloco `with`, Ctrl+C forçado e erro de disco viram mensagem
    clara em vez de um traceback do Python."""

    def __init__(self):
        self.requested = False
        self.immediate = False

    def __enter__(self):
        import signal
        self._signal = signal
        self._previous = signal.getsignal(signal.SIGINT)

        def handler(signum, frame):
            if self.requested or self.immediate:
                raise KeyboardInterrupt
            self.requested = True
            print("\n  Ctrl+C recebido -- terminando o bloco atual e salvando o checkpoint "
                  "(aperte Ctrl+C de novo pra sair na hora).", flush=True)

        signal.signal(signal.SIGINT, handler)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._signal.signal(self._signal.SIGINT, self._previous)
        if exc_type is KeyboardInterrupt:
            print("\nSaindo agora. Nada se perde além do que foi feito desde o último checkpoint "
                  "(se estava na avaliação final, ela recomeça na próxima execução; o treino já está salvo).")
            sys.exit(1)
        if exc_type is not None and issubclass(exc_type, OSError):
            print(f"\nERRO ao gravar/ler arquivo: {exc}. Confira se tem espaço em disco e permissão de escrita "
                  f"na pasta. O último checkpoint salvo continua intacto -- rode de novo depois de resolver.")
            sys.exit(1)
        return False
