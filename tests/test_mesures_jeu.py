"""Niveau 3 du cahier : confrontation au jeu.

Les niveaux 1 et 2 verifient que le noyau est d'accord avec lui-meme — le
solveur retrouve les regimes du NBT, l'integrateur colle a la solution
analytique. Aucun des deux ne dit si les EQUATIONS sont les bonnes.

Ici, chaque assertion rejoue une lecture faite a la main en jeu, consignee dans
`data/mesures/jeu.json`. C'est ce qui rend le lot L2 livrable : « le lot L2
n'est livrable que si au moins une grandeur du niveau 3 a ete confrontee au jeu
et concorde ».

Une mesure qui cesse de concorder est une regression du modele. Elargir la
tolerance pour faire passer le test reviendrait a jeter la seule chose qui
rattache ce simulateur au jeu.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from createsim.model.vehicle import VehicleModel
from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation

MESURES = Path(__file__).resolve().parents[1] / "data" / "mesures" / "jeu.json"
SCHEMATICS = Path(r"C:/Users/Florian/curseforge/minecraft/Instances"
                  r"/La Bonne Compagnie/schematics")


def _pos(text: str) -> tuple[int, int, int]:
    x, y, z = (int(v) for v in text.split(","))
    return (x, y, z)


def _load() -> list[dict]:
    return json.loads(MESURES.read_text(encoding="utf-8"))["mesures"]


def _simulation(entry: dict) -> Simulation:
    path = SCHEMATICS / entry["vaisseau"]
    if not path.is_file():
        pytest.skip("vaisseau hors depot : %s" % entry["vaisseau"])
    sim = Simulation(VehicleModel.load(str(path)), SimOptions())
    for lever, value in (entry.get("commandes") or {}).items():
        sim.set_command(_pos(lever), int(value))
    sim._solve(sim.state)
    return sim


def _network(sim: Simulation, index: int) -> dict:
    budget = sim.report()["stress"]
    for row in budget:
        if row["reseau"] == index:
            return row
    pytest.fail("reseau %d absent du bilan" % index)


ENTRIES = _load()
IDS = [e["id"] for e in ENTRIES]


@pytest.fixture(params=ENTRIES, ids=IDS)
def mesure(request):
    return request.param


def test_chaque_mesure_porte_sa_provenance(mesure):
    """Une mesure sans date ni observateur n'est pas une mesure."""
    for field in ("id", "date", "observateur", "vaisseau", "instrument"):
        assert mesure.get(field), "%s : %s manquant" % (mesure["id"], field)
    assert mesure.get("valide"), "dire ce que la lecture valide, sinon a quoi bon"


def test_le_modele_reproduit_la_mesure(mesure):
    grandeur = mesure["grandeur"]

    if grandeur in ("capacite_su", "stress_su"):
        row = _network(_simulation(mesure), mesure["reseau"])
        assert row[grandeur] == pytest.approx(mesure["attendu"],
                                              abs=mesure["tolerance"]), (
            "%s : %.1f su calcules contre %.1f su lus en jeu"
            % (mesure["id"], row[grandeur], mesure["attendu"]))

    elif grandeur == "regime":
        sim = _simulation(mesure)
        lever, block = _pos(mesure["levier"]), _pos(mesure["bloc"])
        for cran, attendu in sorted(mesure["escalier"].items(),
                                    key=lambda kv: int(kv[0])):
            sim.set_command(lever, int(cran))
            sim._solve(sim.state)
            obtenu = abs(sim.state.speeds.get(block) or 0.0)
            assert obtenu == pytest.approx(attendu, abs=mesure["tolerance"]), (
                "cran %s : %.1f tr/min calcules contre %.1f lus"
                % (cran, obtenu, attendu))

    elif grandeur == "convention_poussee":
        from createsim.sim import forces as F
        sim = _simulation(mesure)
        bearings = sim.bearings.of_type("aeronautics:propeller_bearing")
        speeds = {b.pos: 100.0 for b in bearings}
        poussees = F.propeller_forces(bearings, speeds, sim.tables)
        assert poussees
        for force, bearing in zip(poussees, bearings):
            axe = F.FACING_VEC[bearing.facing]
            produit = sum(a * b for a, b in zip(force.vector, axe))
            assert produit > 0, ("%s : la poussee doit suivre l'axe du palier"
                                 % mesure["id"])
    else:
        pytest.fail("grandeur inconnue : %s" % grandeur)


def test_une_reserve_est_tenue_explicite(mesure):
    """Une mesure a un seul point ne doit pas se faire passer pour une loi."""
    if mesure["id"] == "cachalot-v4-helice-centrale-a-fond":
        assert mesure.get("reserve"), "la loi par voile tient sur un seul point"
    if mesure["grandeur"] == "convention_poussee":
        assert mesure.get("reserve"), "le sens absolu n'est pas encore tranche"


# --- ce que la mesure a change dans le modele -------------------------------
def test_l_impact_d_une_helice_suit_ses_voiles(cargo):
    """Avant la mesure, un palier d'helice coutait 2,0 su/tr quel que soit son
    rotor. Il en coute 2,0 PAR VOILE : un facteur 16 sur le cachalot."""
    from createsim.data.tables import Tables
    tables = Tables.load()
    assert "aeronautics:propeller_bearing" in tables.get(
        "stress.impact_scales_with_sails")


def test_un_rotor_assemble_donne_un_plancher_pas_une_estimation():
    """Rotor assemble : les voiles ne sont plus dans le fichier. Le modele doit
    le DIRE, pas livrer un chiffre seize fois trop petit sans prevenir."""
    cruiser = SCHEMATICS / "c1_air_cruiser.nbt"
    if not cruiser.is_file():
        pytest.skip("vaisseau hors depot")
    report = Simulation(VehicleModel.load(str(cruiser))).report()
    limites = [a for a in report["anomalies"] if a["code"] == "F5.9"]
    assert limites, "deux paliers de ce vaisseau ont un rotor assemble"
    for anomaly in limites:
        assert anomaly["gravite"] == "limite du modele"
        assert "PLANCHER" in anomaly["detail"]


def test_un_reseau_qui_disjoncte_dit_ce_qu_il_demandait(cargo):
    """Sans cela, une surcharge se lit « 0 SU demandes, pas de surcharge » :
    le vaisseau s'arrete et rien n'explique pourquoi."""
    cachalot = SCHEMATICS / "cachalot_volant_v4.nbt"
    if not cachalot.is_file():
        pytest.skip("vaisseau hors depot")
    sim = Simulation(VehicleModel.load(str(cachalot)), SimOptions())
    for lever in ((57, 11, 11), (57, 11, 13), (59, 11, 10)):
        sim.set_command(lever, 0)
    sim._solve(sim.state)

    row = _network(sim, 0)
    assert row["disjoncte"] is True
    assert row["surcharge"] is True
    assert row["stress_su"] == pytest.approx(20480.0, abs=0.5), (
        "les trois helices a fond demandent 2,5 fois la capacite du moulin")
    assert all(abs(v) < 1e-9 for v in sim.state.speeds.values()), \
        "un reseau en surcharge arrete TOUS ses consommateurs"

    anomaly = next(a for a in sim.report()["anomalies"] if a["code"] == "F5.4")
    assert "20480" in anomaly["detail"] and "8192" in anomaly["detail"]
