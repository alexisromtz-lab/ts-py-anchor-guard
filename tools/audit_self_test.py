"""Report the data I/O a module performs while running its `--self-test`.

The README claims that three of the four modules open no data file and no socket during
their self-test, and that `live_oracle` does. A claim about what a program *does not* do
cannot be read off its source: it needs an observer. `sys.addaudithook` is that observer --
every `open`, socket and subprocess event passes through it, including the ones a library
makes on your behalf.

What is excluded, and why:

* events under `sys.prefix` / `sys.executable` -- the interpreter reading its own stdlib;
* opening a `.py` or `.pyc`, and anything under `__pycache__` -- loading code is not
  touching the user's disk, and counting it would make every module guilty of importing.

Everything else is reported. A temp file, a socket, a `Popen`: if it happened, it is here.

Each module is measured in its own process, because an audit hook cannot be uninstalled
and one module's events would otherwise be attributed to the next.

Usage:

    python tools/audit_self_test.py                 # every module in the package
    python tools/audit_self_test.py live_oracle     # one module, verbose
    python tools/audit_self_test.py --json          # machine-readable

RC: 0 conforming -- no module touched data I/O · 1 diverging -- at least one did, and the
README names which · 2 not measured -- the module has no `main()` · 20 bad invocation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MODULOS = ("anchor_oracle", "live_oracle", "subpixel_probe", "viewport_embed")
RC_OK, RC_DIVERGE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20

EVENTOS = ("open", "socket.__new__", "socket.connect", "socket.getaddrinfo",
           "subprocess.Popen", "os.exec", "os.system", "os.posix_spawn")


def _es_carga_de_codigo(evento: str, args: str) -> bool:
    return evento == "open" and (".py'" in args or ".pyc" in args or "__pycache__" in args)


def _es_bytecode_por_fd(evento: str, args: tuple) -> bool:
    """`open(3, 'wb')` on a bare descriptor writes a `.pyc`.

    Importing a module for the first time compiles it and writes the bytecode through a
    descriptor allocator hands out, so the event carries no path and none of the path
    filters above can see it. It shows up once per clone and then never again, which is
    exactly the shape of a flake. The child process runs with `-B` so this should not
    happen at all; the filter stays so that a reader invoking the probe without `-B` gets
    the same answer.
    """
    return (evento == "open" and bool(args) and isinstance(args[0], int)
            and len(args) > 1 and isinstance(args[1], str)
            and ("w" in args[1] or "x" in args[1]))


def _es_dato(evento: str, args: tuple) -> bool:
    """Si el evento es I/O de datos. Se juzga sobre los argumentos del evento, no sobre el
    recorte que se imprime.

    En macOS el Python del sistema cachea el bytecode de una copia en
    `~/Library/Caches/com.apple.python/<ruta>-39.pyc`. Con la copia bajo `$TMPDIR` esa ruta
    pasa de 160 caracteres y el recorte se comia el `.pyc`, de modo que cargar codigo se
    reportaba como leer datos: un falso rojo que solo aparecia en la ruta larga.
    """
    texto = repr(args)
    return (not any(s in texto for s in (sys.prefix, sys.base_prefix, sys.executable))
            and not _es_carga_de_codigo(evento, texto)
            and not _es_bytecode_por_fd(evento, args))


def _sonda(modulo: str) -> int:
    """Run one module's `--self-test` under an audit hook and print the report."""
    import contextlib
    import importlib
    import io

    sys.path.insert(0, str(RAIZ))
    try:
        mod = importlib.import_module(f"ts_py_anchor_guard.{modulo}")
    except ImportError as exc:
        print(json.dumps({"modulo": modulo, "rc": RC_NO_MEDIDO, "motivo": str(exc)}))
        return RC_NO_MEDIDO
    if not hasattr(mod, "main"):
        print(json.dumps({"modulo": modulo, "rc": RC_NO_MEDIDO,
                          "motivo": "el modulo no expone main()"}))
        return RC_NO_MEDIDO

    vistos: list[tuple[str, str, tuple]] = []

    def hook(evento: str, args: tuple) -> None:
        if evento in EVENTOS:
            vistos.append((evento, repr(args), args))

    sys.addaudithook(hook)
    sys.argv = [f"{modulo}.py", "--self-test"]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = mod.main()
    except SystemExit as exc:
        rc = exc.code
    ajenos = [[v[0], v[1][:160]] for v in vistos if _es_dato(v[0], v[2])]
    print(json.dumps({"modulo": modulo, "rc_self_test": rc, "eventos_vistos": len(vistos),
                      "datos_fuera_de_stdlib": ajenos, "n_datos": len(ajenos),
                      "salida": buf.getvalue().strip()[-120:]}, ensure_ascii=False))
    return RC_OK


def _medir(modulo: str) -> dict:
    p = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--sonda", modulo],
                       capture_output=True, text=True, timeout=300)
    for linea in reversed(p.stdout.strip().splitlines()):
        try:
            return json.loads(linea)
        except json.JSONDecodeError:
            continue
    return {"modulo": modulo, "rc": RC_NO_MEDIDO, "motivo": (p.stderr or p.stdout)[-200:]}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--sonda"]:
        return _sonda(args[1]) if len(args) == 2 and args[1] in MODULOS else RC_ARITY
    como_json = "--json" in args
    pedidos = [a for a in args if a != "--json"] or list(MODULOS)
    if any(m not in MODULOS for m in pedidos):
        print(f"uso: audit_self_test.py [{' '.join(MODULOS)}] [--json]", file=sys.stderr)
        return RC_ARITY

    informe = [_medir(m) for m in pedidos]
    if como_json:
        print(json.dumps(informe, indent=2, ensure_ascii=False))
    else:
        for fila in informe:
            if "n_datos" not in fila:
                print(f"{fila['modulo']:16} NO_MEDIDO · {fila.get('motivo', '')}")
                continue
            print(f"{fila['modulo']:16} rc={fila['rc_self_test']} · "
                  f"{fila['n_datos']} evento(s) de datos · {fila['salida']}")
    if any("n_datos" not in f for f in informe):
        return RC_NO_MEDIDO
    return RC_DIVERGE if any(f["n_datos"] for f in informe) else RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
