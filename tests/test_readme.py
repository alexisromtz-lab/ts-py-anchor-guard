"""A published pin is a promise about an object, not a string in a README.

An exact `@vX.Y.Z` must name the version this tree declares; a floating `@vN` must resolve
to the same commit as `v<version>`, or whoever pins the major pointer installs a tree from
another day. Without `.git` — or with a shallow clone that never fetched the tag — the
question is `NO_MEDIDO` and says so: absence and not-fetched are not the same claim.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_RE_CITA = re.compile(r"@v(\d+(?:\.\d+)*)\b")
_RE_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(RAIZ), "--no-pager"] + list(args),
        capture_output=True,
        text=True,
    )


def _citas() -> list:
    return _RE_CITA.findall((RAIZ / "README.md").read_text(encoding="utf-8"))


def _version(texto: str):
    encontrado = _RE_VERSION.search(texto)
    return encontrado.group(1) if encontrado else None


class EtiquetaDelReadmeTest(unittest.TestCase):
    def _version_arbol(self) -> str:
        version = _version((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIsNotNone(version, "pyproject.toml no declara version: nada que medir")
        return version

    def _exigir_arbol_git(self) -> None:
        if not (RAIZ / ".git").exists():
            self.skipTest("NO_MEDIDO: sin .git (sdist, rueda o archivo), una etiqueta no se resuelve")

    def _commit_introduce_la_version(self) -> bool:
        """True si este commit es el salto: su etiqueta se crea despues, nunca antes."""
        padre = _git("show", "HEAD^:pyproject.toml")
        if padre.returncode != 0:
            return True
        return _version(padre.stdout) != self._version_arbol()

    def test_el_readme_no_ensena_una_version_que_el_arbol_no_declara(self) -> None:
        version = self._version_arbol()
        citas = _citas()
        self.assertTrue(citas, "el lector no encuentra ninguna cita: la guarda seria un verde vacio")
        exactas = [c for c in citas if c.count(".") == 2]
        self.assertTrue(exactas, f"el README no ensena una version exacta que vigilar: {citas}")
        for cita in exactas:
            self.assertEqual(cita, version, f"el README ensena @v{cita} y el arbol declara {version}")

    def test_los_punteros_mayores_apuntan_al_arbol_medido(self) -> None:
        """Cualquier grafia del puntero mayor — `v`, `v0` — es una promesa sobre el arbol actual."""
        self._exigir_arbol_git()
        version = self._version_arbol()
        destino = _git("rev-parse", "--verify", "--quiet", f"refs/tags/v{version}^{{commit}}")
        if destino.returncode != 0:
            self.skipTest(f"NO_MEDIDO: `v{version}` no esta en este clon, no hay con que comparar")
        mayores = sorted(
            t for t in _git("tag", "--list").stdout.split() if re.fullmatch(r"v\d*", t)
        )
        self.assertTrue(mayores, "no hay puntero mayor en el repositorio: nada que medir")
        for mayor in mayores:
            puntero = _git("rev-parse", "--verify", "--quiet", f"refs/tags/{mayor}^{{commit}}")
            self.assertEqual(puntero.returncode, 0, f"la etiqueta {mayor} no resuelve a un commit")
            self.assertEqual(
                puntero.stdout.strip(),
                destino.stdout.strip(),
                f"`{mayor}` apunta a {puntero.stdout.strip()[:7]} y v{version} a "
                f"{destino.stdout.strip()[:7]}: quien ate el puntero mayor instala otro arbol",
            )

    def test_la_etiqueta_de_la_version_nombra_un_arbol_que_la_declara(self) -> None:
        self._exigir_arbol_git()
        version = self._version_arbol()
        punta = _git("rev-parse", "--verify", "--quiet", f"refs/tags/v{version}^{{commit}}")
        if punta.returncode != 0:
            if _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
                self.skipTest(
                    f"NO_MEDIDO: clon superficial sin `v{version}`: ausencia y no-traido no se distinguen"
                )
            if self._commit_introduce_la_version():
                self.skipTest(
                    f"NO_MEDIDO: `v{version}` aun no existe y este commit introduce la version"
                )
            self.fail(f"el arbol declara {version} y el repositorio no tiene la etiqueta v{version}")
        manifiesto = _git("show", f"{punta.stdout.strip()}:pyproject.toml")
        self.assertEqual(manifiesto.returncode, 0, f"v{version} no contiene pyproject.toml")
        self.assertEqual(
            _version(manifiesto.stdout),
            version,
            f"v{version} declara {_version(manifiesto.stdout)}: instalar la etiqueta da otro instrumento",
        )

    def test_ninguna_etiqueta_de_version_miente_sobre_el_arbol_que_nombra(self) -> None:
        """Mover una etiqueta exacta es la unica forma de que un pin medido mienta sin editarse."""
        self._exigir_arbol_git()
        etiquetas = [
            t
            for t in _git("tag", "--list", "v*").stdout.split()
            if re.fullmatch(r"v\d+\.\d+\.\d+", t)
        ]
        self.assertTrue(etiquetas, "no hay etiquetas exactas: la guarda seria un verde vacio")
        mentirosas = []
        for tag in etiquetas:
            manifiesto = _git("show", f"{tag}:pyproject.toml")
            if manifiesto.returncode != 0 or _version(manifiesto.stdout) != tag[1:]:
                mentirosas.append(tag)
        self.assertEqual(
            mentirosas,
            [],
            f"etiquetas cuyo arbol no declara la version que su nombre promete: {mentirosas}",
        )

    def test_el_lector_ve_y_discrimina(self) -> None:
        """Un lector que no distingue una cita de otra no mide: se mide a si mismo."""
        self.assertEqual(_cita_de("@v0.9.8"), "0.9.8")
        self.assertEqual(_cita_de("@v0"), "0")
        self.assertIsNone(_cita_de("v0.9.8 sin arroba"))


def _cita_de(texto: str):
    encontrado = _RE_CITA.search(texto)
    return encontrado.group(1) if encontrado else None


if __name__ == "__main__":
    unittest.main()
