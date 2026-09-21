# -*- mode: python ; coding: utf-8 -*-
"""Description PyInstaller de l'executable createsim.

Ne se lance pas directement : `python packaging/build_exe.py` l'appelle, puis
verifie que ce qui en sort demarre, affiche la vue 3D et tient la cadence.

Ce qui est embarque, et pourquoi :

    data/tables      les constantes du jeu, avec leur source : sans elles, rien
    data/scenarios   la bibliotheque de scenarios (menu « scenario »)
    exemples/        les vaisseaux d'exemple, proposes par l'accueil
    assets/          l'icone de la fenetre

Ce qui ne l'est pas : `data/mesures` (les lectures faites en jeu ne servent
qu'a `createsim validate`), les tests, la documentation.

Deux formes, choisies par la variable CREATESIM_ONEFILE :

    dossier (defaut)   dist/createsim/createsim.exe + _internal/
                       demarre en une seconde, se signale moins aux antivirus
    fichier unique     dist/createsim.exe
                       un seul fichier a partager, mais chaque lancement
                       depaquete ~100 Mo dans le dossier temporaire
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent            # noqa: F821  (fourni par PyInstaller)
ONEFILE = os.environ.get("CREATESIM_ONEFILE") == "1"
WINDOWS = sys.platform == "win32"
ICON = ROOT / "assets" / ("createsim.ico" if WINDOWS else "createsim.png")

datas = [
    (str(ROOT / "data" / "tables"), "data/tables"),
    (str(ROOT / "data" / "scenarios"), "data/scenarios"),
    (str(ROOT / "assets" / "createsim.png"), "assets"),
]
datas += [(str(p), "exemples")
          for p in sorted((ROOT / "tests" / "fixtures").glob("*.nbt"))]

a = Analysis(                                                    # noqa: F821
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Rien de tout cela n'est importe par l'application ; les nommer evite
    # qu'un module present sur la machine de construction ne s'invite dans le
    # paquet et ne l'alourdisse de dizaines de Mo.
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "scipy", "pandas",
              "PIL", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)                                                # noqa: F821

if ONEFILE:
    exe = EXE(                                                   # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [],
        name="createsim", console=False, icon=str(ICON), upx=False,
    )
else:
    exe = EXE(                                                   # noqa: F821
        pyz, a.scripts, [], exclude_binaries=True,
        name="createsim", console=False, icon=str(ICON), upx=False,
    )
    coll = COLLECT(                                              # noqa: F821
        exe, a.binaries, a.datas, name="createsim", upx=False,
    )
