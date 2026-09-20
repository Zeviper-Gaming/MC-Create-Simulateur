"""Interface en ligne de commande du noyau.

Le noyau doit tourner sans fenetre : c'est ce qui le rend testable et rejouable
automatiquement, et c'est ce qui rend la non-regression possible.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .data.tables import Tables
from .model.vehicle import VehicleModel
from .sim.state import SimOptions
from .sim.telemetry import Trace
from .sim.tick import Simulation


def _load(path: str, args) -> Simulation:
    tables = Tables.load(getattr(args, "tables", None))
    model = VehicleModel.load(path, tables)
    options = SimOptions(
        altitude=getattr(args, "altitude", 63.0),
        ground_altitude=getattr(args, "sol", 0.0) or 0.0,
        ground_enabled=getattr(args, "sol", None) is not None,
        ground_friction=getattr(args, "friction", 1.0),
        initial_gas=getattr(args, "gaz", "nbt"),
    )
    sim = Simulation(model, options)
    for spec in getattr(args, "commande", None) or []:
        pos, _, value = spec.partition("=")
        key = tuple(int(v) for v in pos.replace("(", "").replace(")", "").split(","))
        sim.set_command(key, int(value))
    return sim


def _emit(payload: dict, out: str | None) -> None:
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print("rapport :", out)
    else:
        print(text)


# ---------------------------------------------------------------------------
def cmd_analyse(args) -> int:
    started = time.perf_counter()
    sim = _load(args.fichier, args)
    report = sim.report()
    report["duree_analyse_s"] = round(time.perf_counter() - started, 3)
    _emit(report, args.json)
    return 0


def cmd_run(args) -> int:
    sim = _load(args.fichier, args)
    trace = Trace(every=args.echantillon)
    started = time.perf_counter()
    sim.run(args.ticks, trace)
    elapsed = time.perf_counter() - started

    if args.csv:
        trace.to_csv(args.csv)
        print("trace :", args.csv, "(%d enregistrements)" % len(trace))

    last = trace.last() or {}
    print("--- %d ticks en %.2f s (%.0f ticks/s) ---"
          % (args.ticks, elapsed, args.ticks / elapsed if elapsed else 0))
    print("altitude   : %8.2f  (depart %.2f)"
          % (last.get("y", 0.0), sim.options.altitude))
    print("vitesse    : %8.3f blocs/s  (h %.3f, v %.3f)"
          % (last.get("vitesse", 0.0), last.get("vitesse_horizontale", 0.0),
             last.get("vitesse_verticale", 0.0)))
    print("gaz        : %8.1f / %d m3"
          % (last.get("gaz_total", 0.0), last.get("gaz_capacite", 0)))
    print("pression   : %8.4f" % last.get("pression", 0.0))
    print("regime max : %8.2f tr/min" % last.get("regime_max", 0.0))
    if args.json:
        _emit(sim.report(), args.json)
    return 0


def cmd_validate(args) -> int:
    from .validation import run_validation
    results = run_validation(Tables.load(getattr(args, "tables", None)),
                             fixtures=args.fixtures)
    ok = True
    for r in results:
        flag = "OK  " if r["passe"] else "ECHEC"
        print("%-5s %-38s %s" % (flag, r["nom"], r["detail"]))
        ok &= r["passe"]
    print("---")
    print("Le lot L0 n'est livrable que si les niveaux 1 et 2 passent : %s"
          % ("ils passent" if ok else "ILS NE PASSENT PAS"))
    return 0 if ok else 1


def cmd_voir(args) -> int:
    try:
        from .view.app import run
    except ImportError as exc:
        print("PySide6 est requis pour la vue 3D : pip install PySide6",
              file=sys.stderr)
        print("(%s)" % exc, file=sys.stderr)
        return 3
    return run(args.fichier, Tables.load(getattr(args, "tables", None)),
               args.bench, args.largeur, args.hauteur)


def cmd_tables(args) -> int:
    from .data import importers
    tables = Tables.load(getattr(args, "tables", None))
    if args.action == "show":
        for key in sorted(tables.entries):
            if args.filtre and args.filtre not in key:
                continue
            entry = tables.entries[key]
            value = entry.value
            if isinstance(value, (list, dict)):
                value = "<%d entrees>" % len(value)
            print("%-44s %-18s %s" % (key, value, entry.source))
        return 0

    result = importers.read_configs(args.fichiers)
    print(result.summary())
    for s in result.skipped:
        print("  ignore :", s)
    changes = importers.diff_against(result, tables)
    if not changes:
        print("aucun ecart : les tables sont a jour")
        return 0
    print("--- %d ecarts ---" % len(changes))
    for c in changes[:40]:
        print("  %-44s %s -> %s" % (c["cle"], c["avant"], c["apres"]))
    if len(changes) > 40:
        print("  ... et %d autres" % (len(changes) - 40))
    if args.appliquer:
        written = importers.apply_to_tables(result, tables.directory)
        for w in written:
            print("ecrit :", w)
    else:
        print("(relancer avec --appliquer pour ecrire les tables)")
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="createsim",
        description="Banc d'essai hors-jeu pour vehicules Create.")
    p.add_argument("--tables", help="dossier des tables de constantes")
    sub = p.add_subparsers(dest="commande_cli", required=True)

    a = sub.add_parser("analyse", help="rapport statique complet")
    a.add_argument("fichier")
    a.add_argument("--json", help="ecrire le rapport dans ce fichier")
    a.add_argument("--altitude", type=float, default=63.0)
    a.add_argument("--friction", type=float, default=1.0)
    a.add_argument("--gaz", choices=("nbt", "vide"), default="nbt")
    a.add_argument("--sol", type=float, default=None)
    a.add_argument("--commande", action="append",
                   metavar="X,Y,Z=N", help="forcer un levier")
    a.set_defaults(func=cmd_analyse)

    r = sub.add_parser("run", help="simuler N ticks et tracer")
    r.add_argument("fichier")
    r.add_argument("--ticks", type=int, default=400)
    r.add_argument("--csv", help="exporter la trace")
    r.add_argument("--json", help="ecrire le rapport final")
    r.add_argument("--altitude", type=float, default=63.0)
    r.add_argument("--friction", type=float, default=1.0)
    r.add_argument("--gaz", choices=("nbt", "vide"), default="nbt")
    r.add_argument("--sol", type=float, default=None)
    r.add_argument("--echantillon", type=int, default=1,
                   help="n'enregistrer qu'un tick sur N")
    r.add_argument("--commande", action="append", metavar="X,Y,Z=N")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("validate", help="niveaux 1 et 2 de validation")
    v.add_argument("--fixtures", default=None)
    v.set_defaults(func=cmd_validate)

    w = sub.add_parser("voir", help="fenetre 3D des blocs (spike)")
    w.add_argument("fichier")
    w.add_argument("--bench", type=float, default=0.0,
                   metavar="SECONDES", help="mesurer la cadence puis sortir")
    w.add_argument("--largeur", type=int, default=1280)
    w.add_argument("--hauteur", type=int, default=720)
    w.set_defaults(func=cmd_voir)

    t = sub.add_parser("tables", help="inspecter ou mettre a jour les tables")
    t.add_argument("action", choices=("show", "import"))
    t.add_argument("fichiers", nargs="*", help="*-server.toml a importer")
    t.add_argument("--filtre", help="ne montrer que les cles contenant ce texte")
    t.add_argument("--appliquer", action="store_true",
                   help="ecrire les tables au lieu d'afficher l'ecart")
    t.set_defaults(func=cmd_tables)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print("fichier introuvable :", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
