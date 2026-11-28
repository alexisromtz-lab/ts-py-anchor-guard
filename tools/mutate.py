"""Apply one-line mutations to the modules and report which ones the suite notices.

A test that reads its fixture and asserts nothing looks exactly like a test that works, as
long as the code is correct. The only way to tell them apart is to break the code and see
whether anything goes red. This script does that: for each curated mutation it copies the
repository to a scratch directory, applies the mutation to the copy, and runs the suite.

Three rules keep the answer honest:

- **A mutation must kill by the test that owns it.** A kill from an unrelated module is a
  flake, not coverage. Each mutant records the site it lives in, and the report flags a kill
  whose failing tests all live in another module's test file.
- **A kill must reproduce.** Every nonzero run is repeated on a fresh copy of the same
  mutation, because a first run is not read-only: tests that spawn an interpreter without
  `-B` leave `__pycache__` behind, and a repeat on that tree measures a warmer subject. A
  mutation that fails on one copy and passes on the other is `FLAKY`, never killed.
- **The repeat compares facts, not locations.** The copies live in different temporary
  directories, so a report that quotes a path differs between two runs of the same failure.
  The location is normalised out before comparing, and what is compared is the whole set of
  failing tests: `A and B` against `A alone` is not a repeat.
- **The scope of a verdict is published, never implied.** A kill is decided first inside the
  module that owns the site, run with `-f` against two fresh copies: if the owner goes red on
  both with the same first mark, the mutation is killed by the test that owns it, and the row
  says `alcance: dueno`. Only a mutation the owner module does not notice pays for the whole
  suite, which is where a `VIVO` or an `[ajeno]` verdict is decided. `--estricto` runs the
  suite for every mutant, which is the same decision taken the expensive way.

Exit code: `0` every applicable mutation was killed or declared unreachable, `1` at least one
mutant survived, `2` something could not be measured, `20` bad invocation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RC_OK, RC_SOBREVIVE, RC_NO_MEDIDO, RC_ARITY = 0, 1, 2, 20

# Each copy of the tree is about 1 MiB, and a mutant holds two of them at once. Below this the
# temp filesystem starts answering `OSError: [Errno 28]` while the suite writes its own scratch
# files, and a red that comes from the disk is indistinguishable from a red that comes from the
# mutation: the run has to refuse before it produces verdicts it cannot pay for. The allowance
# is per worker, because workers run suites side by side and the scratch is written concurrently.
LIBRE_MINIMO = 64 * 1024 * 1024

# (id, module, original text, mutated text, why the mutation matters)
MUTANTES: tuple[tuple[str, str, str, str, str], ...] = (
    ("sp_delta_signo", "ts_py_anchor_guard/subpixel_probe.py",
     "delta = 0.5 * (c_menos - c_mas) / curvatura",
     "delta = -0.5 * (c_menos - c_mas) / curvatura",
     "el signo del refinamiento subpixel"),
    ("sp_sin_clamp", "ts_py_anchor_guard/subpixel_probe.py",
     'recibo["desplazamiento"] = mejor + max(-0.5, min(0.5, delta))',
     'recibo["desplazamiento"] = mejor + delta',
     "el tope de media muestra (inmatable: ver README)"),
    ("sp_curvatura_cero", "ts_py_anchor_guard/subpixel_probe.py",
     "    if curvatura <= 0:", "    if curvatura < 0:",
     "la parabola plana deja de ser NO_MEDIDO (inmatable: ver README)"),
    ("sp_borde_izq", "ts_py_anchor_guard/subpixel_probe.py",
     "    if mejor in (-max_shift, max_shift):", "    if mejor == max_shift:",
     "el borde izquierdo de la ventana de busqueda"),
    ("sp_escala_signo", "ts_py_anchor_guard/subpixel_probe.py",
     '"error_de_escala": -pendiente,', '"error_de_escala": pendiente,',
     "el signo del error de escala por bandas"),
    ("sp_ssd_signo", "ts_py_anchor_guard/subpixel_probe.py",
     "return sum((a[i] - b[i + d]) ** 2 for i in range(lo_a, hi_a))",
     "return sum((a[i] - b[i - d]) ** 2 for i in range(lo_a, hi_a))",
     "el signo del desplazamiento dentro del SSD"),
    ("sp_fase_signo", "ts_py_anchor_guard/subpixel_probe.py",
     "        x = i * escala - fase", "        x = i * escala + fase",
     "el signo de la fase en el perfil sintetico"),
    ("sp_bandas_guarda", "ts_py_anchor_guard/subpixel_probe.py",
     "    if n // bandas < 32:", "    if n // bandas < 0:",
     "el rechazo de bandas demasiado estrechas"),
    ("sp_solape_min", "ts_py_anchor_guard/subpixel_probe.py",
     "    if hi_a - lo_a < 2:", "    if hi_a - lo_a < 0:",
     "el minimo de solape (inmatable: ver README)"),
    ("ve_centro_round", "ts_py_anchor_guard/viewport_embed.py",
     "        (ancho_cuadro - ancho_ventana) // 2,",
     "        round((ancho_cuadro - ancho_ventana) / 2),",
     "el redondeo del margen hacia dentro"),
    ("ve_escala_eje1", "ts_py_anchor_guard/viewport_embed.py",
     "    if escala[0] != 1.0 or escala[1] != 1.0:", "    if escala[0] != 1.0:",
     "el estiramiento en el eje vertical"),
    ("ve_sin_recorte", "ts_py_anchor_guard/viewport_embed.py",
     "    elif not dentro:", "    elif False:",
     "la causa RECORTE"),
    ("ve_entero_cero", "ts_py_anchor_guard/viewport_embed.py",
     "    if valor <= 0:", "    if valor < 0:",
     "el lienzo de lado cero"),
    ("ve_escala_inv", "ts_py_anchor_guard/viewport_embed.py",
     "    escala = (ancho_ventana / ancho, alto_ventana / alto)",
     "    escala = (ancho / ancho_ventana, alto / alto_ventana)",
     "la direccion de la escala"),
    ("ao_round_04", "ts_py_anchor_guard/anchor_oracle.py",
     '"round": math.floor(valor + 0.5)', '"round": math.floor(valor + 0.4)',
     "la politica round en la banda (0.4, 0.5)"),
    ("ao_rel_no_relativo", "ts_py_anchor_guard/anchor_oracle.py",
     "            rel = error / abs(valor) if valor else (0.0 if error == 0 else math.inf)",
     "            rel = error",
     "el error relativo"),
    ("ao_error_sin_abs", "ts_py_anchor_guard/anchor_oracle.py",
     "            error = abs(obtenido - valor)", "            error = obtenido - valor",
     "el valor absoluto del error"),
    ("ao_tolerancia_muda", "ts_py_anchor_guard/anchor_oracle.py",
     "            if error > tolerancia:", "            if error > 1e9:",
     "la comparacion contra la tolerancia"),
    ("ao_literal_pasa", "ts_py_anchor_guard/anchor_oracle.py",
     "        if len(numeros) != len(obtenidos):", "        if False:",
     "el literal devuelto pide un campo en vez de inventar"),
    ("ao_dual_roto", "ts_py_anchor_guard/anchor_oracle.py",
     '        if nombre.partition(".")[0] not in anclas:', '        if nombre not in anclas:',
     "el ancla dual `Nombre.campo`"),
    ("ao_cadena_abre_solo", "ts_py_anchor_guard/anchor_oracle.py",
     "    m[i] = 0\n    j = i + 1\n    while j < n:",
     "    m[i] = 0\n    j = i\n    while j < n:",
     "el cuerpo de una cadena se lee como codigo: `\"cero}\"` cierra un nivel"),
    ("ao_regex_es_division", "ts_py_anchor_guard/anchor_oracle.py",
     "        elif c == \"/\" and _es_inicio_regex(texto, i, m):",
     "        elif False:",
     "un literal de regex con comilla abre una cadena y se traga el archivo"),
    ("ao_separador_no_es_digito", "ts_py_anchor_guard/anchor_oracle.py",
     r"(?:(\d[\d_]*(?:\.\d[\d_]*)?", r"(?:(\d+(?:\.\d+)?",
     "el separador de miles de un numero: `1_000_000` deja de ser un digito"),
    ("ao_censo_sin_denominador", "ts_py_anchor_guard/anchor_oracle.py",
     "    declaradas = len(anclas) + len(motivos)",
     "    declaradas = len(anclas)",
     "el denominador del censo vuelve a ser lo que el lector alcanzo a leer"),
    ("ao_entorno_no_se_nombra", "ts_py_anchor_guard/anchor_oracle.py",
     "            variables = _lee_entorno(ancla[\"cuerpo\"])",
     "            variables = []",
     "la poblacion que depende del entorno se confunde con los huecos del lector"),
    ("ao_entorno_en_el_texto", "ts_py_anchor_guard/anchor_oracle.py",
     "                   if m.start() < len(mascara) and mascara[m.start()]",
     "                   if True",
     "un texto que nombra `process.env.X` se lee como una dependencia"),
    ("ao_entorno_sin_corchetes", "ts_py_anchor_guard/anchor_oracle.py",
     r'''r"(?:\.([A-Za-z_$][\w$]*)|\s*\[\s*[\"']([^\"']+)[\"']\s*\])")''',
     r'''r"(?:\.([A-Za-z_$][\w$]*)|\s*\[\s*[\"'](\d+)[\"']\s*\])")''',
     "la forma `process.env[\"X\"]` deja de contar como entorno"),
    ("ao_texto_con_tolerancia", "ts_py_anchor_guard/anchor_oracle.py",
     "            igual = obtenido == esperado",
     "            igual = abs(len(obtenido) - len(esperado)) <= tolerancia",
     "la igualdad exacta del texto"),
    ("ao_divergen_mudo", "ts_py_anchor_guard/anchor_oracle.py",
     "    if divergen:", "    if False:",
     "el veredicto de divergencia"),
    ("ao_noevaluable_ok", "ts_py_anchor_guard/anchor_oracle.py",
     "    if no_evaluables:", "    if False:",
     "el veredicto de ancla no evaluable"),
    ("lo_sin_flag", "ts_py_anchor_guard/live_oracle.py",
     "    if (mayor, menor) >= _CON_FLAG:", "    if (mayor, menor) >= (99, 0):",
     "la frontera de node que el README publica"),
    ("cli_arity_2", "ts_py_anchor_guard/_cli.py",
     '        self.exit(RC_ARITY, f"{self.prog}: error: {message}\\n")',
     '        self.exit(RC_NO_MEDIDO, f"{self.prog}: error: {message}\\n")',
     "la aridad en la frontera"),
    ("cli_no_traduce", "ts_py_anchor_guard/_cli.py",
     "    except OSError as exc:", "    except ValueError as exc:",
     "la traduccion de insumo faltante"),
    ("au_filtro_py", "tools/audit_self_test.py",
     '    return evento == "open" and (".py\'" in args or ".pyc" in args or "__pycache__" in args)',
     '    return evento == "open" and (".pyc" in args or "__pycache__" in args)',
     "la rama `.py` del filtro de carga de codigo"),
    ("au_fd_solo_w", "tools/audit_self_test.py",
     '            and ("w" in args[1] or "x" in args[1]))',
     '            and "w" in args[1])',
     "el modo exclusivo del bytecode por descriptor"),
    ("au_n_datos_todos", "tools/audit_self_test.py",
     '"datos_fuera_de_stdlib": ajenos, "n_datos": len(ajenos),',
     '"datos_fuera_de_stdlib": ajenos, "n_datos": len(vistos),',
     "el conteo es de eventos ajenos, no de todos"),
    ("au_desconocido_20", "tools/audit_self_test.py",
     "    if any(m not in MODULOS for m in pedidos):",
     "    if False:",
     "el modulo pedido que no existe sale con 20"),
    ("au_sin_B", "tools/audit_self_test.py",
     '    p = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--sonda", modulo],',
     '    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--sonda", modulo],',
     "el -B que mantiene fria la medida de bytecode"),
    ("au_sin_popen", "tools/audit_self_test.py",
     '           "subprocess.Popen", "os.exec", "os.system", "os.posix_spawn")',
     '           "os.exec", "os.system", "os.posix_spawn")',
     "el evento que delata al proceso hijo de live_oracle"),
    ("au_dato_recorte160", "tools/audit_self_test.py",
     "    texto = repr(args)", "    texto = repr(args)[:160]",
     "el filtro que juzga sobre el recorte que imprime"),
    ("au_carga_sin_pyc", "tools/audit_self_test.py",
     'or ".pyc" in args or "__pycache__" in args)', 'or ".PYC" in args or "__pycache__" in args)',
     "el .pyc que no vive bajo __pycache__ (cache del Python del sistema)"),
    ("au_dato_sin_prefijo", "tools/audit_self_test.py",
     "    return (not any(s in texto for s in (sys.prefix, sys.base_prefix, sys.executable))",
     "    return (not any(s in texto for s in ())",
     "la exclusion de la stdlib y del interprete"),
    ("au_dato_sin_fd", "tools/audit_self_test.py",
     "            and not _es_bytecode_por_fd(evento, args))", "            and True)",
     "el bytecode escrito por descriptor, que no lleva ruta"),
    ("ce_sin_fallos", "tools/contrato_censo.py",
     "    return filas, (RC_OK if not fallos else RC_DIVERGE)",
     "    return filas, RC_OK",
     "el censo que nunca puede decir que no"),
    ("ce_celda_vacia", "tools/contrato_censo.py",
     "        (\"subpixel_probe\", RC_DIVERGE, (\"--a\", a, \"--b\", b), RC_NO_MEDIDO, POR_DISENO,",
     "        (\"subpixel_probe\", RC_DIVERGE, (\"--a\", a, \"--b\", b), RC_OK, POR_DISENO,",
     "la celda que se declara vacia en vez de medida"),
    ("lo_caja_llena", "ts_py_anchor_guard/live_oracle.py",
     "        except OSError as fallo:\n            return {}, f\"caja temporal no escribible: {fallo}\"\n        orden =",
     "        except OSError as fallo:\n            raise\n        orden =",
     "el disco lleno vuelve a salir como excepcion"),
    ("cli_choque_escapa", "ts_py_anchor_guard/_cli.py",
     "    except Exception as fallo:  # noqa: BLE001 - the boundary is where a last net belongs",
     "    except ZeroDivisionError as fallo:",
     "el borde deja de traducir el choque: vuelve el 1 que significa dos cosas"),
    ("cli_choque_es_uno", "ts_py_anchor_guard/_cli.py",
     "        print(f\"NO_MEDIDO · FALLA_INTERNA · {type(fallo).__name__}: {fallo}\", file=sys.stderr)\n"
     "        return RC_NO_MEDIDO",
     "        print(f\"NO_MEDIDO · FALLA_INTERNA · {type(fallo).__name__}: {fallo}\", file=sys.stderr)\n"
     "        return RC_DIVERGE",
     "un choque del instrumento se reporta como divergencia del sujeto"),
    ("sp_perfil_escapa", "ts_py_anchor_guard/subpixel_probe.py",
     "    except PerfilInvalido as exc:",
     "    except KeyError as exc:",
     "el perfil invalido vuelve a salir como traceback con rc 1"),
    ("ao_ref_vacia_ok", "ts_py_anchor_guard/anchor_oracle.py",
     "    if not referencia:", "    if False:",
     "una referencia sin nombres vuelve a conformar con cero anclas"),
    ("lo_nulos_conforman", "ts_py_anchor_guard/live_oracle.py",
     "    if not any(v is not None for valores in vivos.values() for v in valores):",
     "    if False:",
     "el lector imprime nulls con rc 0 como si hubiera medido"),
    ("ce_choque_conforma", "tools/contrato_censo.py",
     '        fila["conforme"] = proc.returncode == fila["esperado"] and not fila["choque"]',
     '        fila["conforme"] = proc.returncode == fila["esperado"]',
     "el censo vuelve a aceptar un traceback como la celda de divergencia"),
    ("ao_tol_borde_exclusivo", "ts_py_anchor_guard/anchor_oracle.py",
     "if error > tolerancia:", "if error >= tolerancia:",
     "el borde de la tolerancia pasa de exclusivo a inclusivo: un error igual a la "
     "tolerancia deja de conformar"),
    ("lo_bool_conforma", "ts_py_anchor_guard/live_oracle.py",
     "isinstance(v, (int, float)) and not isinstance(v, bool)) else None",
     "isinstance(v, (int, float))) else None",
     "un `true` de TypeScript se lee como 1: True ya es int en Python"),
    ("lo_probe_typeof", "ts_py_anchor_guard/live_oracle.py",
     "  if (typeof v === \"number\") return Number.isFinite(v) ? v : String(v);\n  return v;",
     "  if (typeof v === \"number\") return Number.isFinite(v) ? v : String(v);\n"
     "  return typeof v;",
     "un nombre ausente vuelve como el texto `undefined` y pasa por medicion"),
    ("lo_motivo_sin_causa", "ts_py_anchor_guard/live_oracle.py",
     'next((linea for linea in reversed(lineas) if "Error" in linea),',
     'next((linea for linea in reversed(lineas) if False),',
     "el motivo vuelve a citar el banner de version de node en vez de la causa"),
    ("lo_frontera_sin_flag", "ts_py_anchor_guard/live_oracle.py",
     "if (mayor, menor) >= _SIN_FLAG:", "if (mayor, menor) > _SIN_FLAG:",
     "la version frontera (la primera que corre sin flag) cae al lado que pasa el flag"),
    ("ce_control_uno_apagado", "tools/contrato_censo.py",
     "if evaluar(falso, raiz=raiz)[1] != RC_DIVERGE:", "if False:",
     "el control negativo de expectativa imposible deja de ejercitarse"),
    ("ce_tabla_choque_invertido", "tools/contrato_censo.py",
     'if f.get("choque") else', 'if not f.get("choque") else',
     "la tabla nombra la causa contraria: un choque se publica como codigo equivocado"),
    ("ao_auto_cae_cuando_se_pide", "ts_py_anchor_guard/anchor_oracle.py",
     '        if backend == "node":\n'
     '            return None, "estatico", ("ORACULO_VIVO_FALLO", motivo), None',
     '        if False:\n'
     '            return None, "estatico", ("ORACULO_VIVO_FALLO", motivo), None',
     "un `node` pedido por el llamante baja al lector estatico: el hueco vuelve a leerse "
     "como verde"),
    ("ao_auto_sin_nombre", "ts_py_anchor_guard/anchor_oracle.py",
     '        return None, "estatico", None, (f"node no leyo la fuente ({motivo}); "\n'
     '                                        f"medido con el lector estatico")',
     '        return None, "estatico", None, None',
     "la caida de `auto` deja de publicar por que: un lector mas debil con el nombre del "
     "mas fuerte"),
    # --- la taxonomia: el rechazo nombra lo que lo detuvo ---
    ("ao_causa_cajon", "ts_py_anchor_guard/anchor_oracle.py",
     '        causa, largo = nombre, encontrado.end() - pos\n    return causa',
     '        causa, largo = nombre, encontrado.end() - pos\n    return "SIMBOLO_NO_NOMBRADO"',
     "el rechazo vuelve al cajon generico: el limite del lector habla con la voz de un "
     "error de sintaxis"),
    ("ao_causa_mas_corta", "ts_py_anchor_guard/anchor_oracle.py",
     "        if encontrado and encontrado.end() - pos > largo:",
     "        if encontrado:",
     "gana el ultimo simbolo y no el mas largo: `!==` se publica como `!`"),
    ("ao_herencia_muda", "ts_py_anchor_guard/anchor_oracle.py",
     'raise FuenteIlegible(f"{base}: {fallo}", causa="BLOQUEADA_POR_ANCLA") from None',
     'raise FuenteIlegible(f"{base}: {fallo}") from None',
     "el ancla que solo apunta se culpa a si misma en vez de nombrar a la que lee"),
    # --- el mapa de entorno: la lectura es una funcion de un despliegue ---
    ("ao_entorno_default", "ts_py_anchor_guard/anchor_oracle.py",
     '            raise FuenteIlegible(f"variable de entorno no declarada: {variable}",\n'
     '                                 causa="VARIABLE_NO_DECLARADA")',
     '            return ""',
     "la variable ausente del mapa se evalua como cadena vacia: el hueco se lee como verde"),
    ("ao_entorno_ignorado", "ts_py_anchor_guard/anchor_oracle.py",
     "        self.mapa = mapa\n",
     "        self.mapa = None\n",
     "el mapa se recibe y no se usa: el censo publica un entorno que no evaluo"),
    ("ao_entorno_sin_publicar", "ts_py_anchor_guard/anchor_oracle.py",
     '        "entorno": dict(sorted(entorno.items())) if entorno else {},',
     '        "entorno": {},',
     "el censo no publica con que mapa midio: dos despliegues del mismo commit son el mismo "
     "recibo"),
    ("ao_entorno_numero", "ts_py_anchor_guard/anchor_oracle.py",
     "    if malos:",
     "    if False:",
     "un mapa con numeros se coacciona a texto: el mapa describe un tipo que el despliegue "
     "no puede tener"),
    # --- los operadores booleanos: la verdad de un texto y el salto del mapa ---
    ("ao_verdad_python", "ts_py_anchor_guard/anchor_oracle.py",
     '    if isinstance(valor, str):\n        return valor != ""',
     '    if isinstance(valor, str):\n        return valor not in ("", "0")',
     "la verdad de un texto se adivina con la regla de Python: un despliegue que exporta "
     "`DRY_RUN=0` recibe el valor por defecto"),
    ("ao_o_logico_invertido", "ts_py_anchor_guard/anchor_oracle.py",
     "            valor = valor if _verdad(valor) else otro",
     "            valor = otro if _verdad(valor) else valor",
     "`||` se comporta como `&&`: el operador devuelve el operando contrario"),
    ("ao_mapa_salto", "ts_py_anchor_guard/anchor_oracle.py",
     '                           _Entorno(anclas, cache, en_curso, mapa), mapa).evaluar()',
     '                           _Entorno(anclas, cache, en_curso, mapa), None).evaluar()',
     "el mapa no cruza el salto de una ancla a otra: el rechazo es identico al honesto y "
     "una variable declarada se lee como hueco"),
    ("ao_nulo_es_ausente", "ts_py_anchor_guard/anchor_oracle.py",
     '        return self.mapa[variable]\n',
     '        if self.mapa[variable] is None:\n'
     '            raise FuenteIlegible(f"variable de entorno no declarada: {variable}",\n'
     '                                 causa="VARIABLE_NO_DECLARADA")\n'
     '        return self.mapa[variable]\n',
     "una clave declarada `null` se lee como clave ausente: la ausencia declarada vuelve a "
     "ser silencio"),

    ("mf_version_ignorada", "ts_py_anchor_guard/manifiesto.py",
     "    if version != VERSION:",
     "    if False:",
     "un manifiesto de una version futura se lee con este lector"),
    ("mf_clave_sobrante", "ts_py_anchor_guard/manifiesto.py",
     "    sobrantes = _desconocidas(par, _CLAVES_PAR)\n    if sobrantes:",
     "    sobrantes = _desconocidas(par, _CLAVES_PAR)\n    if False:",
     "un campo mal escrito deja de nombrarse: la compuerta queda apagada en silencio"),
    ("mf_exigir_no_bool", "ts_py_anchor_guard/manifiesto.py",
     "    if not isinstance(exigir, bool):",
     "    if False:",
     "`exigir_cobertura_total: \"si\"` se lee como encendido por ser cadena no vacia"),
    ("mf_precedencia_max", "ts_py_anchor_guard/manifiesto.py",
     "    if RC_DIVERGE in codigos:\n        return RC_DIVERGE\n"
     "    return RC_NO_MEDIDO if any(c != RC_OK for c in codigos) else RC_OK",
     "    return max(codigos) if codigos else RC_OK",
     "la divergencia de un par queda tapada por el hueco de otro: 2 gana a 1"),
    ("mf_ignoradas_comparadas", "ts_py_anchor_guard/manifiesto.py",
     "        else:\n            ignoradas.append(nombre)",
     "        else:\n            expandida[nombre] = valor",
     "una clave que ningun mapeo alcanza se compara en vez de contarse"),
    ("mf_mapeo_no_consume", "ts_py_anchor_guard/manifiesto.py",
     "        consumidas.add(raiz)",
     "        pass",
     "el contenedor mapeado sigue en la referencia: el par vuelve a ANCLA_NO_EVALUABLE"),
    ("mf_deriva_tapada", "ts_py_anchor_guard/manifiesto.py",
     '        if recibo["rc"] != RC_DIVERGE:',
     "        if True:",
     "un mapeo roto sobrescribe la divergencia medida: el defecto tapa al sujeto"),
    ("mf_cobertura_sin_guardia", "ts_py_anchor_guard/manifiesto.py",
     '    return par.get("cobertura") or {"declaradas": 0, "comparadas": 0, "omitidas": []}',
     '    return par["cobertura"]',
     "un par que se niega antes de la cobertura vuelve a tumbar el recibo entero"),
    ("mf_aviso_no_publicado", "ts_py_anchor_guard/manifiesto.py",
     "    if aviso:\n", "    if False:\n",
     "la caida de `auto` no llega al recibo: el lector que corrio se lee como el que se pidio"),
    ("mf_tolerancia_del_par_ignorada", "ts_py_anchor_guard/manifiesto.py",
     'par.get("tolerancia", 0.0 if tolerancia is None else tolerancia)',
     '(0.0 if tolerancia is None else tolerancia)',
     "la invocacion relaja en silencio la tolerancia que el manifiesto firma"),
    ("mf_exigir_cli_no_rige", "ts_py_anchor_guard/manifiesto.py",
     "or exigir_cobertura_total)",
     "or False)",
     "`--exigir-cobertura-total` se acepta y no enciende nada"),
    # --- el recibo diferencial: dos despliegues del mismo commit ---
    ("ao_valores_sin_poblacion", "ts_py_anchor_guard/anchor_oracle.py",
     '        "valores": dict(sorted(valores.items())),',
     '        "valores": {},',
     "la superficie de valores se publica vacia: un diferencial compara dos conjuntos "
     "vacios y llama invariancia al acuerdo"),
    ("ao_valores_de_mas", "ts_py_anchor_guard/anchor_oracle.py",
     "                valores[nombre] = evaluar(anclas, nombre, cache=cache, entorno=entorno)",
     "                valores[nombre] = evaluar(anclas, nombre, cache=cache, entorno=entorno)\n"
     "                valores.setdefault('_', None)",
     "`valores` deja de ser una por evaluable: un denominador que no cuadra con su poblacion"),
    ("ao_huella_sin_mapa", "ts_py_anchor_guard/anchor_oracle.py",
     '    canon = json.dumps(mapa, sort_keys=True, ensure_ascii=False, separators=(",", ":"))',
     '    canon = "{}"',
     "la huella deja de identificar el mapa: dos despliegues distintos citan la misma"),
    ("ao_invariante_por_defecto", "ts_py_anchor_guard/anchor_oracle.py",
     '        "invariantes": len(comunes) - len(filas),',
     '        "invariantes": len(comunes),',
     "lo que cambia se cuenta tambien como invariante: cambian + invariantes != comunes"),
    ("ao_solo_en_uno_se_infla", "ts_py_anchor_guard/anchor_oracle.py",
     '        "solo_en_destino": sorted(set(valores_destino) - set(valores_base)),',
     '        "solo_en_destino": [],',
     "el ancla ilegible en la base desaparece del recibo: su ausencia se lee como lectura"),
    ("ao_exigir_no_rige", "ts_py_anchor_guard/anchor_oracle.py",
     '        if recibo["rc"] == RC_OK and args.exigir_invariancia and recibo["cambian"]:',
     '        if False:',
     "`--exigir-invariancia` se acepta y no enciende nada: la deriva pasa con rc 0"),
    # --- el resumen acotado: el techo es la propiedad ---
    ("re_sin_techo", "ts_py_anchor_guard/_resumen.py",
     "    if len(_crudo(valor)) <= presupuesto:\n        return valor, False",
     "    if True:\n        return valor, False",
     "el resumen deja de acotar: la linea vuelve a medir el recibo entero"),
    ("re_lista_sin_muestra", "ts_py_anchor_guard/_resumen.py",
     "        return (tabla, True) if tabla is not None else _muestra(valor, presupuesto)",
     "        return _escueto(valor), True",
     "las filas se tiran enteras: el recibo dice cuantas cambiaron y no nombra ninguna"),
    ("re_muestra_sin_resto", "ts_py_anchor_guard/_resumen.py",
     '        recorte["_resto"] = len(valor) - len(cabeza)',
     '        recorte["_resto"] = 0',
     "una muestra parcial se publica como lista completa: lo que no viajo deja de nombrarse"),
    ("re_bytes_no_pesado", "ts_py_anchor_guard/_resumen.py",
     '    print(_crudo(resumir(recibo, bytes_original=len(crudo.replace("\\n", "").strip()'
     '.encode()))))',
     "    print(_crudo(resumir(recibo)))",
     "`bytes` mide la serializacion resumida: el resumen deja de precio al recibo que reemplazo"),
)

# El modulo de prueba que le corresponde a cada fuente, indexado por la ruta de la fuente.
# No se deriva del nombre: `_cli.py` se prueba en `test_contrato_cli.py`, y suponer lo
# contrario marcaria como ajeno un muerto que si es del sitio. La ruta va completa porque
# no toda fuente vive en el paquete: el probe esta en `tools/`.
MODULOS_DE_PRUEBA = {
    "ts_py_anchor_guard/subpixel_probe.py": "subpixel_probe",
    "ts_py_anchor_guard/viewport_embed.py": "viewport_embed",
    "ts_py_anchor_guard/anchor_oracle.py": "anchor_oracle",
    "ts_py_anchor_guard/live_oracle.py": "live_oracle",
    "ts_py_anchor_guard/_cli.py": "contrato_cli",
    "ts_py_anchor_guard/manifiesto.py": "manifiesto",
    "ts_py_anchor_guard/_resumen.py": "resumen",
    "tools/audit_self_test.py": "audit_self_test",
    "tools/contrato_censo.py": "contrato_censo",
}

# Un test que afirma "este texto aparece una vez" mide justo lo que la mutacion cambia: con
# el dentro, todos los mutantes mueren por la misma razon y la tasa se vuelve un 25/25 falso.
# Se excluye de la copia y se deja un tripwire por si aparece otro.
PRUEBAS_DEL_ARNES = ("tests/test_mutate.py",)

# Mutantes que ningun test puede matar: la aritmetica hace inalcanzable la guarda. Se
# declaran aqui para que el informe los cuente aparte en vez de llamarlos huecos.
INALCANZABLES = {
    "sp_sin_clamp": "con c0 el minimo, |c_menos - c_mas| <= c_menos - 2*c0 + c_mas",
    "sp_curvatura_cero": "curvatura == 0 exige empate triple con c0 minimo",
    "sp_solape_min": "2*max_shift + 8 > min(len) ya rechaza esos insumos antes",
    "au_fd_solo_w": "medido: el bytecode por descriptor se abre 'wb'; ningun evento usa 'xb'",
}


def _persiste_bytecode() -> bool:
    """Whether this interpreter writes a `.pyc` for a cold import of a fresh module.

    `au_sin_B` deletes the `-B` that keeps the probe's child from caching what it imports, so
    what the mutant can move is whatever the interpreter caches. Measured on this machine:
    3.12.13 writes two files for a one-line module, the CLT 3.9.6 writes none. Where none are
    written, the flag has no observable effect and no test can kill its removal.
    """
    with tempfile.TemporaryDirectory(prefix="pyc-") as caja:
        pkg = Path(caja) / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "m.py").write_text("X = 1\n")
        subprocess.run([sys.executable, "-c", "import pkg.m"], cwd=caja, check=False,
                       capture_output=True)
        return any(Path(caja).rglob("*.pyc"))


if not _persiste_bytecode():
    INALCANZABLES["au_sin_B"] = (
        "equivalente: este interprete no escribe .pyc, asi que quitar el -B no cambia nada "
        "observable (medido: 0 archivos para un import frio)")



def _libre(ruta: Path) -> int | None:
    """Free bytes on the filesystem holding `ruta`, or `None` if it cannot be asked."""
    try:
        return shutil.disk_usage(ruta).free
    except OSError:
        return None


def _copiar(destino: Path) -> None:
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(RAIZ, destino,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    for relativa in PRUEBAS_DEL_ARNES:
        (destino / relativa).unlink(missing_ok=True)


def _mutar(destino_del_arbol: Path, sitio: str, viejo: str, nuevo: str) -> str:
    """Copia el arbol y aplica una mutacion. Devuelve "" o el motivo de no aplicarse.

    La copia se rehace entera en cada corrida a proposito: repetir sobre el arbol que la
    primera corrida ya entibio no repite el experimento.
    """
    _copiar(destino_del_arbol)
    destino = destino_del_arbol / sitio
    texto = destino.read_text()
    if texto.count(viejo) != 1:
        return f"el patron aparece {texto.count(viejo)} veces"
    destino.write_text(texto.replace(viejo, nuevo))
    return ""


def _correr(raiz: Path, solo: str | None = None, failfast: bool = False) -> tuple[int, str]:
    """Corre la suite en `raiz`, o solo el modulo `solo` cuando se nombra.

    `failfast` corta en el primer fallo: se usa en la etapa del dueno, donde lo que se afirma es
    "el test que posee el sitio mata al mutante", y el primer fallo de ese modulo ya lo afirma.
    """
    orden = [sys.executable, "-B", "-m", "unittest"]
    if failfast:
        orden.append("-f")
    orden += [f"tests.test_{solo}"] if solo else ["discover", "-s", "tests", "-t", "."]
    proc = subprocess.run(orden, cwd=raiz, capture_output=True, text=True, timeout=1800)
    # Donde vive la copia es una entrada de la corrida, no una observacion: sin esto, dos
    # corridas que fallan el mismo test difieren en la ruta temporal y parecen no reproducir.
    err = (proc.stderr or "").strip()
    for raiz_de_la_corrida in {str(raiz.parent), str(raiz.parent.resolve())}:
        err = err.replace(raiz_de_la_corrida, "<corrida>")
    return proc.returncode, err


def _marcas(err: str) -> tuple[str, ...]:
    """Todas las rutas `tests.test_x.Clase` que fallaron, en orden.

    A nivel de clase y no de metodo: `unittest` escribe el metodo antes del parentesis y la
    clase dentro, asi que el nombre del metodo no llega a la marca. Es la misma granularidad
    en las dos etapas, y por eso las dos lecturas se pueden comparar.

    Se comparan las dos corridas por esta lista y no por el primer fallo: dos corridas que
    fallan A y B, y A sola, no reprodujeron el mismo hecho aunque empiecen igual.
    """
    marcas = []
    for linea in err.splitlines():
        if linea.startswith(("FAIL:", "ERROR:")):
            resto = linea.split(":", 1)[1].strip()
            if "(" in resto and ")" in resto:
                marcas.append(resto[resto.index("(") + 1:resto.index(")")])
            else:
                marcas.append(resto.split(" ")[0])
    return tuple(marcas)


def _marca(err: str) -> str:
    """La ruta del primer fallo, o vacio. Es lo que se publica como quien mato al mutante."""
    marcas = _marcas(err)
    return marcas[0] if marcas else ""


def _marca_propia(sitio: str, err: str) -> str:
    """El primer fallo del test que posee el sitio, o el primero si ninguno es suyo.

    El reporte nombra al dueno del mutante: si un test ajeno falla antes que el propio, imprimir
    el ajeno al lado de un veredicto `propio` hace ilegible quien mato al mutante.
    """
    marcas = _marcas(err)
    if not marcas:
        return ""
    esperado = f"tests.test_{MODULOS_DE_PRUEBA[sitio]}."
    return next((m for m in marcas if m.startswith(esperado)), marcas[0])


def _veredicto(sitio: str, err: str) -> str:
    """`propio` si algun test del mismo modulo mata al mutante, `ajeno` si ninguno.

    Un muerto por un test de otro modulo no es cobertura de este mutante: es el azar de una
    corrida. Se nombra para que nadie lo sume.
    """
    marcas = _marcas(err)
    if not marcas:
        return "sin_marca"
    esperado = f"tests.test_{MODULOS_DE_PRUEBA[sitio]}."
    return "propio" if any(m.startswith(esperado) for m in marcas) else "ajeno"


def _juzgar(caja: Path, mutante: tuple[str, str, str, str, str],
            estricto: bool = False) -> dict:
    """Decide un mutante en su propia caja y devuelve su fila.

    Dos etapas. La primera corre solo el modulo dueno, con `-f`, sobre dos copias frescas: si
    ambas se ponen rojas con la misma marca, el mutante esta muerto por el test que lo posee y
    la suite entera no puede agregar nada a esa afirmacion. Si el dueno pasa, el mutante es
    invisible para quien lo posee, y ahi si hace falta la suite: es la unica corrida que puede
    decir `VIVO` (nadie lo mata) o `[ajeno]` (lo mata un test que no es suyo).
    """
    mid, sitio, viejo, nuevo, motivo = mutante
    dueno = MODULOS_DE_PRUEBA[sitio]
    t0 = time.time()
    fila = {"id": mid, "sitio": sitio, "motivo": motivo, "alcance": "suite"}
    copia = caja / mid
    no_aplica = _mutar(copia, sitio, viejo, nuevo)
    if no_aplica:
        return {**fila, "estado": "NO_APLICABLE", "detalle": no_aplica, "alcance": ""}

    if not estricto:
        rc1, err1 = _correr(copia, solo=dueno, failfast=True)
        if rc1 != 0:
            repeticion = caja / f"{mid}-repeticion"
            if _mutar(repeticion, sitio, viejo, nuevo):
                return {**fila, "estado": "NO_APLICABLE", "detalle": "el patron ya no aplica",
                        "alcance": "dueno"}
            rc2, err2 = _correr(repeticion, solo=dueno, failfast=True)
            shutil.rmtree(repeticion, ignore_errors=True)
            shutil.rmtree(copia, ignore_errors=True)
            if rc2 == 0:
                estado, detalle = "FLAKY", f"{_marca(err1)} (no reproduce)"
            elif _marcas(err1) != _marcas(err2):
                estado, detalle = "FLAKY", f"{_marca(err1)} / {_marca(err2)}"
            else:
                estado, detalle = "MUERTO", _marca_propia(sitio, err1)
            return {**fila, "estado": estado, "detalle": detalle, "alcance": "dueno",
                    "veredicto": _veredicto(sitio, err1) if estado == "MUERTO" else "",
                    "segundos": round(time.time() - t0, 1)}

    if _mutar(copia, sitio, viejo, nuevo):
        return {**fila, "estado": "NO_APLICABLE", "detalle": "el patron ya no aplica"}
    rc1, err1 = _correr(copia)
    if rc1 == 0:
        estado, detalle = "VIVO", ""
    else:
        copia2 = caja / f"{mid}-repeticion"
        if _mutar(copia2, sitio, viejo, nuevo):
            estado, detalle = "NO_APLICABLE", "el patron ya no aplica"
        else:
            rc2, err2 = _correr(copia2)
            if rc2 == 0:
                estado, detalle = "FLAKY", f"{_marca(err1)} (no reproduce)"
            elif _marcas(err1) != _marcas(err2):
                estado, detalle = "FLAKY", f"{_marca(err1)} / {_marca(err2)}"
            elif any(m.startswith("tests.test_mutate.") for m in _marcas(err1)):
                estado, detalle = "AUTORREFERENTE", _marca(err1)
            else:
                estado, detalle = "MUERTO", _marca_propia(sitio, err1)
        shutil.rmtree(copia2, ignore_errors=True)
    shutil.rmtree(copia, ignore_errors=True)
    return {**fila, "estado": estado, "detalle": detalle,
            "veredicto": _veredicto(sitio, err1) if estado == "MUERTO" else "",
            "autorreferente": estado == "AUTORREFERENTE",
            "segundos": round(time.time() - t0, 1)}


def _repartir(caja: Path, pendientes: list[tuple], trabajadores: int,
              estricto: bool) -> tuple[list[dict], list[dict]]:
    """Corre los mutantes en paralelo y devuelve las filas en el orden de la tabla.

    El trabajo es esperar procesos, no calcular: los trabajadores son hebras porque cada uno
    esta bloqueado en un `subprocess.run`. Una caja por mutante, asi que ninguno ve el arbol
    que otro entibio. El orden de las filas es el de la tabla y no el de terminacion: un
    reporte que cambia de orden entre corridas es un reporte que no se puede comparar.
    """
    filas, rotos = {}, {}
    with ThreadPoolExecutor(max_workers=trabajadores) as piscina:
        futuros = {piscina.submit(_juzgar, caja, m, estricto): m[0] for m in pendientes}
        for futuro in as_completed(futuros):
            mid = futuros[futuro]
            try:
                filas[mid] = futuro.result()
            except Exception as fallo:  # noqa: BLE001 -- se publica como NO_MEDIDO, no se traga
                rotos[mid] = f"{type(fallo).__name__}: {fallo}"
    ordenadas = [filas[m[0]] for m in pendientes if m[0] in filas]
    return ordenadas, [{"id": k, "detalle": v} for k, v in rotos.items()]


def main(argv: list[str]) -> int:
    solo, como_json, estricto, trabajadores = set(), False, False, 0
    resto = list(argv)
    while resto:
        arg = resto.pop(0)
        if arg == "--json":
            como_json = True
        elif arg == "--estricto":
            estricto = True
        elif arg == "--trabajadores":
            if not resto or not resto[0].isdigit() or int(resto[0]) < 1:
                print("uso: mutate.py [ID ...] [--json] [--estricto] [--trabajadores N]",
                      file=sys.stderr)
                return RC_ARITY
            trabajadores = int(resto.pop(0))
        elif arg.startswith("-"):
            print("uso: mutate.py [ID ...] [--json] [--estricto] [--trabajadores N]",
                  file=sys.stderr)
            return RC_ARITY
        else:
            solo.add(arg)
    trabajadores = trabajadores or min(os.cpu_count() or 1, 4)
    desconocidos = solo - {m[0] for m in MUTANTES}
    if desconocidos:
        print(f"mutante desconocido: {', '.join(sorted(desconocidos))}", file=sys.stderr)
        return RC_ARITY

    with tempfile.TemporaryDirectory(prefix="mut-") as tmp:
        libre = _libre(Path(tmp))
        necesario = LIBRE_MINIMO * trabajadores
        if libre is None or libre < necesario:
            cuanto = "NO_MEDIDO" if libre is None else f"{libre // (1024 * 1024)} MiB"
            print(f"NO_MEDIDO · el disco temporal tiene {cuanto} y la corrida necesita "
                  f"{necesario // (1024 * 1024)} MiB ({trabajadores} trabajador(es) x "
                  f"{LIBRE_MINIMO // (1024 * 1024)} MiB): una suite sin sitio produce rojos "
                  f"que no son del mutante", file=sys.stderr)
            return RC_NO_MEDIDO
        base = Path(tmp) / "base"
        _copiar(base)
        rc, err = _correr(base)
        if rc != 0:
            print(f"NO_MEDIDO · la base sin mutar no esta verde: {err[-400:]}", file=sys.stderr)
            return RC_NO_MEDIDO
        shutil.rmtree(base, ignore_errors=True)

        pendientes = [m for m in MUTANTES if not solo or m[0] in solo]
        filas, rotos = _repartir(Path(tmp), pendientes, trabajadores, estricto)
        if rotos:
            print(f"NO_MEDIDO · el arnes no pudo juzgar {', '.join(r['id'] for r in rotos)}: "
                  f"{rotos[0]['detalle']}", file=sys.stderr)
            return RC_NO_MEDIDO

    vivos = [f for f in filas if f["estado"] == "VIVO"]
    flojos = [f for f in filas if f["estado"] == "FLAKY"]
    aplicables = [f for f in filas if f["estado"] != "NO_APLICABLE"]
    huecos = [f["id"] for f in vivos if f["id"] not in INALCANZABLES]
    ajenos = [f["id"] for f in filas if f["veredicto"] == "ajeno"]

    if como_json:
        print(json.dumps({"filas": filas, "vivos": [f["id"] for f in vivos],
                          "huecos": huecos, "ajenos": ajenos,
                          "trabajadores": trabajadores, "estricto": estricto,
                          "inalcanzables": sorted(INALCANZABLES)},
                         indent=1, ensure_ascii=False))
    else:
        for f in filas:
            extra = f" [{f['veredicto']}]" if f["veredicto"] else ""
            alcance = f" ({f['alcance']})" if f["alcance"] else ""
            print(f"{f['id']:22} {f['estado']:12} {f['detalle']}{extra}{alcance}")
        print(f"\naplicables: {len(aplicables)} · muertos: "
              f"{len(aplicables) - len(vivos) - len(flojos)} · vivos: {len(vivos)} · "
              f"flaky: {len(flojos)}")
        print(f"inalcanzables declarados: {', '.join(sorted(INALCANZABLES))}")
        print(f"huecos de cobertura: {', '.join(huecos) if huecos else 'ninguno'}")
        print(f"muertos por un test ajeno: {', '.join(ajenos) if ajenos else 'ninguno'}")
        por_dueno = sum(1 for f in filas if f["alcance"] == "dueno")
        por_suite = sum(1 for f in filas if f["alcance"] == "suite")
        print(f"alcance: {por_dueno} decididos por su modulo dueno · "
              f"{por_suite} por la suite · {trabajadores} trabajador(es)")

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
