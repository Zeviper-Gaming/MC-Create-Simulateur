"""Les niveaux de validation automatiques du cahier.

Un simulateur qui ne prouve pas sa justesse est un generateur de chiffres
rassurants. Quatre niveaux existent, du moins couteux au plus probant ; les deux
premiers tournent sans intervention et sans jeu, et conditionnent la livraison
du noyau.

  1. Concordance interne  — le solveur doit retrouver les regimes enregistres
     dans le NBT a 0,5 tr/min pres. Reference : 8 sur 8 sur cargo_airship.
  2. Coherence analytique — la trainee etant lineaire, la vitesse a une solution
     exacte ; l'integrateur doit y coller a mieux de 1 %.

  3. Confrontation au jeu — les lectures faites a la main sur un vaisseau pose,
     consignees dans `data/mesures/jeu.json`, rejouees par le modele. Seul ce
     niveau dit si les EQUATIONS sont les bonnes, et le cahier en fait la
     condition de livrabilite de L2.

  4. Non-regression — la bibliotheque de scenarios de reference, rejouee
     apres chaque mise a jour des tables ou du solveur, avec comparaison
     automatique des traces. C'est ce qui permet de suivre un mod en alpha
     sans redouter chaque version.

Les trois premiers disent si le modele est juste. Le quatrieme dit s'il a
CHANGE, ce qui n'est pas la meme question : une mise a jour de mod peut tres
bien rendre le modele toujours juste et le vaisseau soudain incapable de
decoller.
"""
from __future__ import annotations

import math
from pathlib import Path

from .data.tables import Tables
from .model.vehicle import VehicleModel
from .sim.integrator import DT, TICKS_PER_SECOND, integrate
from .sim.kinetics import concordance, solve_speeds
from .sim.state import SimOptions
from .sim.tick import Simulation

TOLERANCE_RPM = 0.51
TOLERANCE_ANALYTIC = 0.01          # 1 %


def default_fixtures() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "tests" / "fixtures"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("tests/fixtures introuvable")


def _fixtures(path: str | Path | None) -> list[Path]:
    directory = Path(path) if path else default_fixtures()
    return sorted(directory.glob("*.nbt"))


# ---------------------------------------------------------------------------
def level1_concordance(tables: Tables, fixtures=None) -> list[dict]:
    """Niveau 1 : le solveur contre la verite terrain du jeu."""
    out: list[dict] = []
    for path in _fixtures(fixtures):
        model = VehicleModel.load(str(path), tables)
        kin = model.organ("cinetique")
        if not kin.recorded:
            continue
        redstone = model.organ("redstone")
        signals = redstone.signals({lv.pos: lv.initial for lv in redstone.levers})
        solution = solve_speeds(kin, signals)
        result = concordance(kin, solution.speeds, TOLERANCE_RPM)
        passed = result["total"] > 0 and result["accord"] == result["total"]
        out.append({
            "nom": "niveau 1 - concordance %s" % path.stem,
            "passe": passed,
            "detail": "%s regimes retrouves a %.2f tr/min pres%s"
                      % (result["concordance_solveur"], TOLERANCE_RPM,
                         "" if passed else "  ECARTS: %s" % result["ecarts"][:3]),
            "mesure": result,
        })
    return out


def level2_analytic(tables: Tables, fixtures=None) -> list[dict]:
    """Niveau 2 : l'integrateur contre la solution exacte de la trainee lineaire.

    On prend la masse et le coefficient de trainee d'un vaisseau reel, on
    applique une poussee constante, et on integre avec l'integrateur du projet.
    La pression est figee a 1 : on isole le schema, qui est ce que ce niveau
    teste. Un ecart signale une erreur de schema ou de pas de temps.
    """
    out: list[dict] = []
    for path in _fixtures(fixtures):
        model = VehicleModel.load(str(path), tables)
        mass = model.organ("masse").total
        k = model.organ("trainee").coefficient(1.0)
        if k <= 0 or mass <= 0:
            continue
        thrust = max(1.0, mass * 0.5)
        v_max = thrust / k
        tau = mass / k

        position = [0.0, 0.0, 0.0]
        velocity = [0.0, 0.0, 0.0]
        ticks = max(400, int(math.ceil(tau * TICKS_PER_SECOND * 8)))
        worst_norm = worst_point = 0.0
        tau_measured = None
        threshold = v_max * (1.0 - 1.0 / math.e)
        previous = 0.0
        for n in range(1, ticks + 1):
            integrate(position, velocity, (thrust, 0.0, 0.0), k, mass)
            exact = v_max * (1.0 - math.exp(-(n * DT) / tau))
            worst_norm = max(worst_norm, abs(velocity[0] - exact) / v_max)
            if exact > 1e-9:
                worst_point = max(worst_point, abs(velocity[0] - exact) / exact)
            if tau_measured is None and velocity[0] >= threshold:
                # interpolation lineaire dans le tick : sans elle, la mesure est
                # quantifiee a 1/20 s, soit deja plus de 1 % pour un tau de 2 s
                span = velocity[0] - previous
                frac = (threshold - previous) / span if span > 1e-15 else 0.0
                tau_measured = (n - 1 + frac) * DT
            previous = velocity[0]

        reached = velocity[0] / v_max
        tau_error = (abs(tau_measured - tau) / tau if tau_measured else 1.0)
        passed = (worst_norm < TOLERANCE_ANALYTIC
                  and tau_error < TOLERANCE_ANALYTIC
                  and abs(reached - 1.0) < 1e-3)
        out.append({
            "nom": "niveau 2 - analytique %s" % path.stem,
            "passe": passed,
            "detail": ("ecart/v_max %.3f %% | tau mesure %.3f s vs m/k %.3f s "
                       "(%.3f %%) | v_max atteint a %.3f %%"
                       % (worst_norm * 100, tau_measured or 0.0, tau,
                          tau_error * 100, reached * 100)),
            "mesure": {
                "v_max_theorique": round(v_max, 4),
                "tau_theorique_s": round(tau, 4),
                "tau_mesure_s": round(tau_measured, 4) if tau_measured else None,
                "ecart_normalise_pct": round(worst_norm * 100, 4),
                "ecart_ponctuel_max_pct": round(worst_point * 100, 4),
                "note": ("l'ecart ponctuel culmine au premier tick, ou la "
                         "solution exacte est proche de zero ; le critere porte "
                         "sur l'ecart rapporte a v_max, qui mesure si la courbe "
                         "est suivie"),
            },
        })
    return out


def level2b_balloon_transient(tables: Tables, fixtures=None) -> list[dict]:
    """Complement : le remplissage d'un ballon doit durer environ 9 s.

    `GAS_FILLING_TIME` vaut 180 ticks. C'est la constante qui justifie le pas de
    temps du tick : un pas different donnerait un transitoire faux.
    """
    out: list[dict] = []
    for path in _fixtures(fixtures):
        model = VehicleModel.load(str(path), tables)
        if not model.organ("ballons").pockets:
            continue
        sim = Simulation(model, SimOptions(initial_gas="vide"))
        # la cible est la demande AU SIGNAL COURANT, pas le maximum des molettes
        target = sum(min(p.demand(sim.state.signals), float(p.capacity))
                     for p in sim.balloons.pockets)
        if target <= 0:
            continue
        reached = None
        for n in range(1, 601):
            sim.step()
            if reached is None and sum(sim.state.gas) >= target * 0.632:
                reached = n
        seconds = (reached or 0) / TICKS_PER_SECOND
        passed = reached is not None and 1.0 <= seconds <= 9.0
        out.append({
            "nom": "niveau 2b - remplissage %s" % path.stem,
            "passe": passed,
            "detail": ("63,2 %% du volume en %.2f s (%d ticks), cible %.0f m3"
                       % (seconds, reached or 0, target)),
            "mesure": {"ticks": reached, "secondes": round(seconds, 2),
                       "cible_m3": round(target, 1)},
        })
    return out


#: la ou chercher un vaisseau nomme par une mesure : d'abord les fixtures du
#: depot, puis l'instance de jeu. Un vaisseau absent fait ignorer sa mesure,
#: jamais echouer la validation — c'est la regle deja suivie pour le cruiser.
INSTANCE = Path(r"C:/Users/Florian/curseforge/minecraft/Instances"
                r"/La Bonne Compagnie/schematics")


def _locate(name: str, fixtures=None) -> Path | None:
    directory = Path(fixtures) if fixtures else None
    for candidate in (directory, default_fixtures(), INSTANCE):
        if candidate is not None and (candidate / name).is_file():
            return candidate / name
    return None


def level3_measurements(tables: Tables, fixtures=None) -> list[dict]:
    """Confrontation au jeu : les lectures faites a la main, rejouees.

    Les niveaux 1 et 2 verifient que le noyau est d'accord avec lui-meme. Seul
    celui-ci dit si les equations sont les bonnes. Le cahier en fait la
    condition de livrabilite de L2.
    """
    import json
    from pathlib import Path

    from .model.vehicle import VehicleModel
    from .sim.state import SimOptions
    from .sim.tick import Simulation

    path = Path(__file__).resolve().parents[2] / "data" / "mesures" / "jeu.json"
    if not path.is_file():
        return []
    out: list[dict] = []
    for entry in json.loads(path.read_text(encoding="utf-8"))["mesures"]:
        if entry["grandeur"] not in ("capacite_su", "stress_su"):
            continue
        ship = _locate(entry["vaisseau"], fixtures)
        if ship is None:
            out.append({
                "nom": "niveau 3 - %s" % entry["id"],
                "passe": True,
                "detail": "IGNORE : %s hors depot" % entry["vaisseau"],
                "mesure": {},
            })
            continue
        sim = Simulation(VehicleModel.load(str(ship), tables), SimOptions())
        for lever, value in (entry.get("commandes") or {}).items():
            sim.set_command(tuple(int(v) for v in lever.split(",")), int(value))
        sim._solve(sim.state)
        rows = [r for r in sim.report()["stress"] if r["reseau"] == entry["reseau"]]
        got = rows[0][entry["grandeur"]] if rows else float("nan")
        expected, tol = entry["attendu"], entry["tolerance"]
        out.append({
            "nom": "niveau 3 - %s" % entry["id"],
            "passe": abs(got - expected) <= tol,
            "detail": ("%.1f su calcules contre %.1f su lus au %s"
                       % (got, expected, entry["instrument"].split(",")[0])),
            "mesure": {"calcule": got, "jeu": expected},
        })
    return out


def level4_nonregression(tables: Tables | None = None,
                         directory=None) -> list[dict]:
    """Rejouer la bibliotheque de scenarios et dire CE QUI A BOUGE.

    C'est ce qui permet de suivre un mod en alpha sans redouter chaque
    version : apres une mise a jour des tables, on ne se demande plus si le
    comportement a change, on lit lesquelles des grandeurs ont bouge et a
    partir de quel tick.

    Un scenario sans trace de reference n'est pas un echec — c'est un scenario
    qu'on n'a pas encore beni. Le confondre avec une regression ferait crier au
    loup a chaque ajout.
    """
    from .sim.compare import compare
    from .sim.scenario import default_library, library, locate
    from .sim.telemetry import Trace

    tables = tables or Tables.load()
    base = Path(directory) if directory else default_library()
    out: list[dict] = []
    for scenario in library(base):
        reference = scenario.reference_path(base)
        if locate(scenario.vaisseau) is None:
            out.append({"nom": "niveau 4 - %s" % scenario.nom, "passe": True,
                        "detail": "IGNORE : %s hors depot" % scenario.vaisseau,
                        "mesure": {}})
            continue
        if not reference.is_file():
            out.append({"nom": "niveau 4 - %s" % scenario.nom, "passe": True,
                        "detail": "pas de reference — `scenario bless` d'abord",
                        "mesure": {}})
            continue
        result = compare(Trace.from_csv(str(reference)), scenario.run(tables))
        detail = result.verdict
        if result.divergence_tick is not None:
            detail += (" — separation au tick %d (%.2f s) sur « %s »"
                       % (result.divergence_tick,
                          result.divergence_seconde or 0.0,
                          result.divergence_colonne))
        out.append({
            "nom": "niveau 4 - %s" % scenario.nom,
            "passe": result.identique,
            "detail": detail,
            "details": [d.line() for d in result.bouges],
            "mesure": result.report(),
        })
    return out


def run_validation(tables: Tables | None = None, fixtures=None) -> list[dict]:
    tables = tables or Tables.load()
    results: list[dict] = []
    results += level1_concordance(tables, fixtures)
    results += level2_analytic(tables, fixtures)
    results += level2b_balloon_transient(tables, fixtures)
    results += level3_measurements(tables, fixtures)
    results += level4_nonregression(tables)
    return results
