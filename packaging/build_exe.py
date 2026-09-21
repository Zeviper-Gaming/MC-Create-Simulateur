"""Construit l'executable autonome, puis verifie qu'il fonctionne.

    python packaging/build_exe.py                # dossier : dist/createsim/
    python packaging/build_exe.py --onefile      # un seul fichier : dist/createsim.exe
    python packaging/build_exe.py --zip          # + dist/createsim-<systeme>.zip
    python packaging/build_exe.py --no-smoke     # sans la verification

Prerequis : `pip install ".[build]"` (PySide6 et PyInstaller). PyInstaller ne
compile pas pour un autre systeme : l'executable Windows se construit sous
Windows, et ainsi de suite.

La verification n'est pas un luxe. Un paquet PyInstaller qui se construit sans
erreur peut demarrer sur une fenetre vide — il suffit qu'un plugin Qt ou un
fichier de donnees manque — et on ne s'en apercoit qu'en l'ouvrant. Trois
essais, executes sur l'executable construit et non sur les sources :

    1. il ouvre un vaisseau d'exemple et photographie sa fenetre (vue 3D comprise)
    2. il tient la cadence obligatoire de 20 ticks/s, rendu inclus
    3. il ouvre l'accueil et y trouve ses exemples embarques

Chacun tourne avec sa propre configuration jetable : la verification ne touche
ni a vos fichiers recents ni a votre journal.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "createsim.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
EXAMPLE = ROOT / "tests" / "fixtures" / "cargo_airship.nbt"
SYSTEM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
EXE_NAME = "createsim.exe" if sys.platform == "win32" else "createsim"

#: en dessous, une vue 3D n'a pas ete dessinee : un PNG vide pese quelques centaines d'octets
MIN_CAPTURE_BYTES = 20_000


def executable(onefile: bool) -> Path:
    return DIST / EXE_NAME if onefile else DIST / "createsim" / EXE_NAME


def folder_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def build(onefile: bool, clean: bool) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller est absent.  pip install \".[build]\"", file=sys.stderr)
        return 3
    env = dict(os.environ)
    env["CREATESIM_ONEFILE"] = "1" if onefile else "0"
    command = [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
               "--distpath", str(DIST), "--workpath", str(WORK)]
    if clean:
        command.append("--clean")
    print("construction :", " ".join(command[2:]))
    begin = time.perf_counter()
    result = subprocess.run(command, cwd=str(ROOT), env=env)
    if result.returncode != 0:
        print("PyInstaller a echoue (code %d)" % result.returncode, file=sys.stderr)
        return result.returncode
    print("construit en %.0f s" % (time.perf_counter() - begin))
    return 0


class Run:
    """Ce qu'un lancement de l'executable a produit."""

    def __init__(self, result, home: Path):
        self.code = result.returncode
        log = home / "createsim.log"
        #: sortie standard ET journal. Lance depuis un terminal ou par un script,
        #: l'executable ecrit sur la sortie qu'on lui donne ; double-clique, il
        #: n'en a pas et ecrit dans le journal. Un test qui ne lirait que l'un
        #: des deux echouerait selon la facon dont on l'a lance.
        self.text = (result.stdout or "") + (result.stderr or "") + (
            log.read_text(encoding="utf-8", errors="replace") if log.is_file() else "")


def run_exe(exe: Path, args: list[str], home: Path, timeout: float = 240.0) -> Run:
    env = dict(os.environ)
    env["CREATESIM_HOME"] = str(home)
    env.pop("CREATESIM_SCHEMATICS", None)
    result = subprocess.run([str(exe)] + args, env=env, timeout=timeout,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    return Run(result, home)


def smoke(exe: Path) -> bool:
    """Trois essais sur l'executable. Renvoie vrai s'ils passent tous."""
    ok = True
    runs: list[Run] = []
    with tempfile.TemporaryDirectory(prefix="createsim-smoke-") as tmp:
        tmp = Path(tmp)

        # 1. un vaisseau s'ouvre et sa fenetre, vue 3D comprise, se dessine
        png = tmp / "vaisseau.png"
        run = run_exe(exe, [str(EXAMPLE), "--capture", str(png)], tmp / "h1")
        runs.append(run)
        size = png.stat().st_size if png.is_file() else 0
        passed = run.code == 0 and size >= MIN_CAPTURE_BYTES
        print("  %s  ouvre un vaisseau et dessine sa fenetre (%d octets, code %d)"
              % ("OK   " if passed else "ECHEC", size, run.code))
        if not passed:
            print(run.text)
        ok &= passed

        # 2. la cadence obligatoire, rendu compris
        run = run_exe(exe, [str(EXAMPLE), "--bench", "2"], tmp / "h2")
        runs.append(run)
        match = re.search(r"boucle\s*:\s*(\d+) tours/s", run.text)
        rate = int(match.group(1)) if match else 0
        passed = run.code == 0 and rate >= 20
        print("  %s  tient les 20 ticks/s obligatoires : %d tours/s (code %d)"
              % ("OK   " if passed else "ECHEC", rate, run.code))
        if not passed:
            print(run.text)
        ok &= passed

        # 3. l'accueil trouve ses exemples embarques
        png = tmp / "accueil.png"
        run = run_exe(exe, ["--capture", str(png)], tmp / "h3")
        runs.append(run)
        size = png.stat().st_size if png.is_file() else 0
        passed = run.code == 0 and size >= MIN_CAPTURE_BYTES // 4
        print("  %s  ouvre l'accueil (%d octets, code %d)"
              % ("OK   " if passed else "ECHEC", size, run.code))
        if not passed:
            print(run.text)
        ok &= passed

        # une trace d'erreur que le code de sortie n'aurait pas revelee
        for index, run in enumerate(runs, 1):
            if "Traceback" in run.text:
                print("  ECHEC  trace d'erreur dans l'essai %d :" % index)
                print(run.text)
                ok = False
    return ok


def make_zip(onefile: bool) -> Path:
    target = executable(onefile)
    archive = DIST / ("createsim-%s" % SYSTEM)
    if onefile:
        staging = DIST / "_zip"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        shutil.copy2(target, staging / target.name)
        result = shutil.make_archive(str(archive), "zip", str(staging))
        shutil.rmtree(staging, ignore_errors=True)
    else:
        result = shutil.make_archive(str(archive), "zip", str(DIST), "createsim")
    return Path(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--onefile", action="store_true",
                        help="un seul fichier plutot qu'un dossier")
    parser.add_argument("--zip", action="store_true", help="produire une archive .zip")
    parser.add_argument("--no-smoke", action="store_true",
                        help="ne pas verifier l'executable construit")
    parser.add_argument("--clean", action="store_true",
                        help="repartir de zero (efface le cache de PyInstaller)")
    parser.add_argument("--skip-build", action="store_true",
                        help="ne pas reconstruire : verifier / archiver l'existant")
    args = parser.parse_args(argv)

    if not args.skip_build:
        code = build(args.onefile, args.clean)
        if code:
            return code
    exe = executable(args.onefile)
    if not exe.is_file():
        print("executable introuvable :", exe, file=sys.stderr)
        return 2
    print("executable   : %s  (%.0f Mo au total)"
          % (exe, folder_size(exe.parent if not args.onefile else exe) / 1e6))

    if not args.no_smoke:
        print("verification :")
        if not smoke(exe):
            print("L'EXECUTABLE NE PASSE PAS SA VERIFICATION", file=sys.stderr)
            return 1
    if args.zip:
        archive = make_zip(args.onefile)
        print("archive      : %s  (%.0f Mo)" % (archive, archive.stat().st_size / 1e6))
    print("pret : %s" % exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
