"""Point d'entree graphique : l'executable, `createsim-gui`, et `createsim` seul.

C'est ce que lance un double-clic sur `createsim.exe`, et c'est aussi ce que
recoit l'executable quand on lui glisse un `.nbt` dessus : Windows passe alors
le chemin en premier argument.

    createsim.exe                    accueil : recents, schematics, exemples
    createsim.exe vaisseau.nbt       ouvre directement ce vaisseau
    createsim.exe a.nbt --bench 5    mesure la cadence pendant 5 s puis sort
    createsim.exe a.nbt --capture x.png   photographie la fenetre puis sort

Le module n'importe pas Qt : `--help` et `--version` marchent sans PySide6.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__, config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="createsim",
        description="Banc d'essai hors-jeu pour vehicules Create. Sans "
                    "argument, ouvre l'accueil.")
    p.add_argument("fichiers", nargs="*", metavar="fichier.nbt",
                   help="vaisseau a ouvrir ; un seul est ouvert a la fois")
    p.add_argument("--tables", help="dossier des tables de constantes")
    p.add_argument("--largeur", type=int, default=1280)
    p.add_argument("--hauteur", type=int, default=720)
    p.add_argument("--bench", type=float, default=0.0, metavar="SECONDES",
                   help="mesurer la cadence de la boucle puis sortir")
    p.add_argument("--capture", metavar="PNG",
                   help="enregistrer la fenetre dans un PNG puis sortir "
                        "(diagnostic : ne photographie que la fenetre)")
    p.add_argument("--version", action="version",
                   version="createsim %s" % __version__)
    return p


def _set_app_id() -> None:
    """Windows regroupe la barre des taches par identifiant d'application. Sans
    le nommer, lance depuis Python, l'outil porte l'icone de `python.exe`."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "createsim.banc-d-essai")
    except Exception:                                             # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    # Avant tout `print` : dans un executable sans console, stdout vaut None.
    config.prepare_streams()
    args = build_parser().parse_args(argv)
    _set_app_id()

    try:
        from .view import launcher
    except ImportError as exc:
        print("PySide6 est requis pour la fenetre : pip install PySide6",
              file=sys.stderr)
        print("(%s)" % exc, file=sys.stderr)
        return 3

    from .data.tables import TableError, Tables
    try:
        tables = Tables.load(args.tables)
    except TableError as exc:
        print("tables introuvables :", exc, file=sys.stderr)
        return 4

    return launcher.run(args.fichiers, tables, args.bench, args.capture,
                        args.largeur, args.hauteur)


if __name__ == "__main__":
    raise SystemExit(main())
