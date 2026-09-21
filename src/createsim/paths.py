"""Ou vivent les ressources : depuis les sources, ou depuis un executable.

Le noyau cherchait ses tables en remontant depuis son propre fichier jusqu'a un
dossier `data/tables`. Ca marche depuis un clone du depot, et ca marche par
chance dans un executable PyInstaller, ou les ressources sont depaquetees a cote
du code. Ce module rend la regle explicite : un seul endroit dit ou est la
racine des ressources, et l'executable et le depot la partagent.

    depot         <racine>/data/tables   <racine>/tests/fixtures   <racine>/assets
    executable    <_internal>/data/tables  <_internal>/exemples     <_internal>/assets

Les exemples s'appellent `tests/fixtures` dans le depot et `exemples` dans
l'executable : un utilisateur n'a pas de dossier `tests`, et « exemples » lui
dit a quoi ils servent.
"""
from __future__ import annotations

import sys
from pathlib import Path


def frozen() -> bool:
    """Vrai dans un executable PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """La racine des ressources.

    Executable : le dossier ou PyInstaller a depose `data/` et le reste
    (`sys._MEIPASS`, soit `_internal/` en mode dossier). Sources : le premier
    parent de ce fichier qui contient `data/tables/manifest.json`.
    """
    if frozen():
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent)
    for parent in Path(__file__).resolve().parents:
        if (parent / "data" / "tables" / "manifest.json").is_file():
            return parent
    raise FileNotFoundError(
        "racine des ressources introuvable en remontant depuis %s" % __file__)


def data_dir() -> Path:
    return bundle_root() / "data"


def examples_dir() -> Path | None:
    """Les vaisseaux d'exemple, ou `None` s'il n'y en a pas."""
    root = bundle_root()
    for candidate in (root / "exemples", root / "tests" / "fixtures"):
        if candidate.is_dir() and any(candidate.glob("*.nbt")):
            return candidate
    return None


def asset(name: str) -> Path | None:
    """Un fichier de `assets/` (icone), ou `None` s'il est absent."""
    candidate = bundle_root() / "assets" / name
    return candidate if candidate.is_file() else None
