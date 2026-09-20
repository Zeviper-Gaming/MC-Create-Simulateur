"""Les niveaux de validation automatiques du cahier.

Un simulateur qui ne prouve pas sa justesse est un generateur de chiffres
rassurants. Quatre niveaux existent, du moins couteux au plus probant ; les deux
premiers tournent sans intervention et sans jeu, et conditionnent la livraison
du noyau.

  1. Concordance interne  — le solveur doit retrouver les regimes enregistres
     dans le NBT a 0,5 tr/min pres. Reference : 8 sur 8 sur cargo_airship.
  2. Coherence analytique — la trainee etant lineaire, la vitesse a une solution
     exacte ; l'integrateur doit y coller a mieux de 1 %.

Les niveaux 3 (confrontation au jeu) et 4 (non-regression sur une bibliotheque
de scenarios) demandent une mesure humaine ou un corpus : ils ne sont pas ici.
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


def run_validation(tables: Tables | None = None, fixtures=None) -> list[dict]:
    tables = tables or Tables.load()
    results: list[dict] = []
    results += level1_concordance(tables, fixtures)
    results += level2_analytic(tables, fixtures)
    results += level2b_balloon_transient(tables, fixtures)
    return results
