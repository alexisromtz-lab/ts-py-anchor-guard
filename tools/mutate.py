"""Apply one-line mutations to the modules and report which ones the suite notices.

A test that reads its fixture and asserts nothing looks exactly like a test that works, as
long as the code is correct. The only way to tell them apart is to break the code and see
whether anything goes red. This script does that: for each curated mutation it copies the
repository to a scratch directory, applies the mutation to the copy, and runs the suite.

Two rules keep the answer honest:

- **A mutation must kill by the test that owns it.** A kill from an unrelated module is a
  flake, not coverage. Each mutant records the site it lives in, and the report flags a kill
  whose failing test lives in another module's test file.
- **A kill must reproduce.** Every nonzero run is repeated on the same copy; a mutation that
  fails once and passes the second time is reported as `FLAKY`, never as killed.

Exit code: `0` every applicable mutation was killed or declared unreachable, `1` at least one
mutant survived, `2` something could not be measured, `20` bad invocation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RC_OK, RC_SOBREVIVE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20

# (id, module, original text, mutated text, why the mutation matters)
MUTANTES: tuple[tuple[str, str, str, str, str], ...] = (
    ("sp_delta_signo", "subpixel_probe.py",
     "delta = 0.5 * (c_menos - c_mas) / curvatura",
     "delta = -0.5 * (c_menos - c_mas) / curvatura",
     "el signo del refinamiento subpixel"),
    ("sp_sin_clamp", "subpixel_probe.py",
     'recibo["desplazamiento"] = mejor + max(-0.5, min(0.5, delta))',
     'recibo["desplazamiento"] = mejor + delta',
     "el tope de media muestra (inmatable: ver README)"),
    ("sp_curvatura_cero", "subpixel_probe.py",
     "    if curvatura <= 0:", "    if curvatura < 0:",
     "la parabola plana deja de ser NO_MEDIDO (inmatable: ver README)"),
    ("sp_borde_izq", "subpixel_probe.py",
     "    if mejor in (-max_shift, max_shift):", "    if mejor == max_shift:",
     "el borde izquierdo de la ventana de busqueda"),
    ("sp_escala_signo", "subpixel_probe.py",
     '"error_de_escala": -pendiente,', '"error_de_escala": pendiente,',
     "el signo del error de escala por bandas"),
    ("sp_ssd_signo", "subpixel_probe.py",
     "return sum((a[i] - b[i + d]) ** 2 for i in range(lo_a, hi_a))",
     "return sum((a[i] - b[i - d]) ** 2 for i in range(lo_a, hi_a))",
     "el signo del desplazamiento dentro del SSD"),
    ("sp_fase_signo", "subpixel_probe.py",
     "        x = i * escala - fase", "        x = i * escala + fase",
     "el signo de la fase en el perfil sintetico"),
    ("sp_bandas_guarda", "subpixel_probe.py",
     "    if n // bandas < 32:", "    if n // bandas < 0:",
     "el rechazo de bandas demasiado estrechas"),
    ("sp_solape_min", "subpixel_probe.py",
     "    if hi_a - lo_a < 2:", "    if hi_a - lo_a < 0:",
     "el minimo de solape (inmatable: ver README)"),
    ("ve_centro_round", "viewport_embed.py",
     "        (ancho_cuadro - ancho_ventana) // 2,",
     "        round((ancho_cuadro - ancho_ventana) / 2),",
     "el redondeo del margen hacia dentro"),
    ("ve_escala_eje1", "viewport_embed.py",
     "    if escala[0] != 1.0 or escala[1] != 1.0:", "    if escala[0] != 1.0:",
     "el estiramiento en el eje vertical"),
    ("ve_sin_recorte", "viewport_embed.py",
     "    elif not dentro:", "    elif False:",
     "la causa RECORTE"),
    ("ve_entero_cero", "viewport_embed.py",
     "    if valor <= 0:", "    if valor < 0:",
     "el lienzo de lado cero"),
    ("ve_escala_inv", "viewport_embed.py",
     "    escala = (ancho_ventana / ancho, alto_ventana / alto)",
     "    escala = (ancho / ancho_ventana, alto / alto_ventana)",
     "la direccion de la escala"),
    ("ao_round_04", "anchor_oracle.py",
     '"round": math.floor(valor + 0.5)', '"round": math.floor(valor + 0.4)',
     "la politica round en la banda (0.4, 0.5)"),
    ("ao_rel_no_relativo", "anchor_oracle.py",
     "            rel = error / abs(valor) if valor else (0.0 if error == 0 else math.inf)",
     "            rel = error",
     "el error relativo"),
    ("ao_error_sin_abs", "anchor_oracle.py",
     "            error = abs(obtenido - valor)", "            error = obtenido - valor",
     "el valor absoluto del error"),
    ("ao_tolerancia_muda", "anchor_oracle.py",
     "            if error > tolerancia:", "            if error > 1e9:",
     "la comparacion contra la tolerancia"),
    ("ao_literal_pasa", "anchor_oracle.py",
     "        if len(numeros) != len(obtenidos):", "        if False:",
     "el literal devuelto pide un campo en vez de inventar"),
    ("ao_dual_roto", "anchor_oracle.py",
     '        if nombre.partition(".")[0] not in anclas:', '        if nombre not in anclas:',
     "el ancla dual `Nombre.campo`"),
    ("ao_divergen_mudo", "anchor_oracle.py",
     "    if divergen:", "    if False:",
     "el veredicto de divergencia"),
    ("ao_noevaluable_ok", "anchor_oracle.py",
     "    if no_evaluables:", "    if False:",
     "el veredicto de ancla no evaluable"),
    ("lo_sin_flag", "live_oracle.py",
     "    if (mayor, menor) >= _CON_FLAG:", "    if (mayor, menor) >= (99, 0):",
     "la frontera de node que el README publica"),
    ("cli_arity_2", "_cli.py",
     '        self.exit(RC_ARITY, f"{self.prog}: error: {message}\\n")',
     '        self.exit(RC_NO_MEDIDO, f"{self.prog}: error: {message}\\n")',
     "la aridad en la frontera"),
    ("cli_no_traduce", "_cli.py",
     "    except OSError as exc:", "    except ValueError as exc:",
     "la traduccion de insumo faltante"),
)

# Mutantes que ningun test puede matar: la aritmetica hace inalcanzable la guarda. Se
# declaran aqui para que el informe los cuente aparte en vez de llamarlos huecos.
# El modulo de prueba que le corresponde a cada fuente. No se deriva del nombre: `_cli.py`
# se prueba en `test_contrato_cli.py`, y suponer lo contrario marcaria como ajeno un muerto
# que si es del sitio.
MODULOS_DE_PRUEBA = {
    "subpixel_probe.py": "subpixel_probe",
    "viewport_embed.py": "viewport_embed",
    "anchor_oracle.py": "anchor_oracle",
    "live_oracle.py": "live_oracle",
    "_cli.py": "contrato_cli",
}

# Un test que afirma "este texto aparece una vez" mide justo lo que la mutacion cambia: con
# el dentro, los 25 mutantes mueren por la misma razon y la tasa se vuelve un 25/25 falso.
# Se excluye de la copia y se deja un tripwire por si aparece otro.
PRUEBAS_DEL_ARNES = ("tests/test_mutate.py",)

INALCANZABLES = {
    "sp_sin_clamp": "con c0 el minimo, |c_menos - c_mas| <= c_menos - 2*c0 + c_mas",
    "sp_curvatura_cero": "curvatura == 0 exige empate triple con c0 minimo",
    "sp_solape_min": "2*max_shift + 8 > min(len) ya rechaza esos insumos antes",
}


def _copiar(destino: Path) -> None:
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(RAIZ, destino,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    for relativa in PRUEBAS_DEL_ARNES:
        (destino / relativa).unlink(missing_ok=True)


def _correr(raiz: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=raiz, capture_output=True, text=True, timeout=1800)
    return proc.returncode, (proc.stderr or "").strip()


def _marca(err: str) -> str:
    """La ruta `tests.test_x.Clase.test_y` del primer fallo, o vacio.

    unittest escribe `FAIL: nombre (ruta.completa)`; el nombre suelto no dice de que modulo
    es el test, y sin el modulo no se puede saber si el mutante lo mato quien debia.
    """
    for linea in err.splitlines():
        if linea.startswith(("FAIL:", "ERROR:")):
            resto = linea.split(":", 1)[1].strip()
            if "(" in resto and resto.endswith(")"):
                return resto[resto.index("(") + 1:-1]
            return resto.split(" ")[0]
    return ""


def _veredicto(sitio: str, err: str) -> str:
    """`propio` si mata un test del mismo modulo, `ajeno` si no.

    Un muerto por un test de otro modulo no es cobertura de este mutante: es el azar de una
    corrida. Se nombra para que nadie lo sume.
    """
    marca = _marca(err)
    if not marca:
        return "sin_marca"
    esperado = f"tests.test_{MODULOS_DE_PRUEBA[sitio]}."
    return "propio" if marca.startswith(esperado) else "ajeno"


def main(argv: list[str]) -> int:
    solo = {a for a in argv if not a.startswith("-")}
    como_json = "--json" in argv
    if any(a.startswith("-") and a != "--json" for a in argv):
        print("uso: mutate.py [ID ...] [--json]", file=sys.stderr)
        return RC_ARITY
    desconocidos = solo - {m[0] for m in MUTANTES}
    if desconocidos:
        print(f"mutante desconocido: {', '.join(sorted(desconocidos))}", file=sys.stderr)
        return RC_ARITY

    with tempfile.TemporaryDirectory(prefix="mut-") as tmp:
        base = Path(tmp) / "base"
        _copiar(base)
        rc, err = _correr(base)
        if rc != 0:
            print(f"NO_MEDIDO · la base sin mutar no esta verde: {err[-400:]}", file=sys.stderr)
            return RC_NO_MEDIDO

        filas = []
        for mid, sitio, viejo, nuevo, motivo in MUTANTES:
            if solo and mid not in solo:
                continue
            copia = Path(tmp) / mid
            _copiar(copia)
            destino = copia / "ts_py_anchor_guard" / sitio
            texto = destino.read_text()
            if texto.count(viejo) != 1:
                filas.append({"id": mid, "estado": "NO_APLICABLE",
                              "detalle": f"el patron aparece {texto.count(viejo)} veces",
                              "sitio": sitio, "motivo": motivo})
                continue
            destino.write_text(texto.replace(viejo, nuevo))
            t0 = time.time()
            rc1, err1 = _correr(copia)
            if rc1 == 0:
                estado, detalle = "VIVO", ""
            else:
                rc2, err2 = _correr(copia)
                if rc2 == 0:
                    estado, detalle = "FLAKY", f"{_marca(err1)} (no reproduce)"
                elif _marca(err1) != _marca(err2):
                    estado, detalle = "FLAKY", f"{_marca(err1)} / {_marca(err2)}"
                elif _marca(err1).startswith("tests.test_mutate."):
                    estado, detalle = "AUTORREFERENTE", _marca(err1)
                else:
                    estado, detalle = "MUERTO", _marca(err1)
            filas.append({"id": mid, "estado": estado, "detalle": detalle,
                          "sitio": sitio, "motivo": motivo,
                          "veredicto": _veredicto(sitio, err1) if estado == "MUERTO" else "",
                          "autorreferente": estado == "AUTORREFERENTE",
                          "segundos": round(time.time() - t0, 1)})
            shutil.rmtree(copia)

    vivos = [f for f in filas if f["estado"] == "VIVO"]
    flojos = [f for f in filas if f["estado"] == "FLAKY"]
    aplicables = [f for f in filas if f["estado"] != "NO_APLICABLE"]
    huecos = [f["id"] for f in vivos if f["id"] not in INALCANZABLES]
    ajenos = [f["id"] for f in filas if f["veredicto"] == "ajeno"]

    if como_json:
        print(json.dumps({"filas": filas, "vivos": [f["id"] for f in vivos],
                          "huecos": huecos, "ajenos": ajenos,
                          "inalcanzables": sorted(INALCANZABLES)},
                         indent=1, ensure_ascii=False))
    else:
        for f in filas:
            extra = f" [{f['veredicto']}]" if f["veredicto"] else ""
            print(f"{f['id']:22} {f['estado']:12} {f['detalle']}{extra}")
        print(f"\naplicables: {len(aplicables)} · muertos: "
              f"{len(aplicables) - len(vivos) - len(flojos)} · vivos: {len(vivos)} · "
              f"flaky: {len(flojos)}")
        print(f"inalcanzables declarados: {', '.join(sorted(INALCANZABLES))}")
        print(f"huecos de cobertura: {', '.join(huecos) if huecos else 'ninguno'}")
        print(f"muertos por un test ajeno: {', '.join(ajenos) if ajenos else 'ninguno'}")

    autorref = [f["id"] for f in filas if f["estado"] == "AUTORREFERENTE"]
    if autorref:
        print(f"NO_MEDIDO · el arnes se mide a si mismo en {', '.join(autorref)}: "
              f"el test que afirma la forma del texto no puede juzgar una mutacion del texto",
              file=sys.stderr)
        return RC_NO_MEDIDO
    if flojos:
        print("NO_MEDIDO · corrida no determinista: repite antes de creer la cifra",
              file=sys.stderr)
        return RC_NO_MEDIDO
    return RC_SOBREVIVE if huecos else RC_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
