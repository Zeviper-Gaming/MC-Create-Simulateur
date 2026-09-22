"""La boucle de simulation : tick, dynamique du gaz, equilibre, performance."""
from __future__ import annotations

import math
import time

import pytest

from createsim.sim.forces import gas_nudge
from createsim.sim.state import SimOptions
from createsim.sim.telemetry import BASE_COLUMNS, Trace
from createsim.sim.tick import Simulation


def test_un_tick_avance_d_un_vingtieme_de_seconde(sim):
    assert sim.state.tick == 0
    sim.step()
    assert sim.state.tick == 1
    assert sim.state.seconds == pytest.approx(0.05)


def test_remise_a_zero_jette_l_etat_et_garde_le_modele(sim):
    depart = list(sim.state.position)
    identite = id(sim.model)
    sim.run(200)
    assert sim.state.position != depart

    sim.reset()
    assert sim.state.tick == 0
    assert sim.state.position == depart
    assert id(sim.model) == identite, "le modele ne doit pas etre relu"


def test_le_ballon_met_environ_neuf_secondes_a_se_remplir(cargo):
    """180 ticks : c'est la constante qui impose le pas de temps du tick."""
    sim = Simulation(cargo, SimOptions(initial_gas="vide"))
    cible = sum(min(p.demand(sim.state.signals), float(p.capacity))
                for p in sim.balloons.pockets)
    assert cible > 0

    atteint = None
    for n in range(1, 401):
        sim.step()
        if atteint is None and sum(sim.state.gas) >= cible * 0.632:
            atteint = n
    assert atteint is not None
    assert 2.0 <= atteint / 20.0 <= 9.0, "63,2 %% en %.2f s" % (atteint / 20.0)
    assert sum(sim.state.gas) == pytest.approx(cible, rel=0.01)


def test_le_surplus_de_gaz_est_perdu():
    """scale = min(capacite/cible, 1) : demander plus que la poche ne donne rien."""
    class T:
        def get(self, k):
            return {"forces.gas_filling_time": 180.0,
                    "forces.gas_emptying_time": 180.0,
                    "forces.gas_responsiveness_factor": 5.0,
                    "forces.gas_responsiveness_range": 0.05}[k]

    q = 0.0
    for _ in range(2000):
        q += gas_nudge(q, 5000.0, 1000.0, T())
    assert q == pytest.approx(1000.0, rel=1e-6), "plafonne a la capacite"


def test_le_gaz_se_vide_aussi():
    class T:
        def get(self, k):
            return {"forces.gas_filling_time": 180.0,
                    "forces.gas_emptying_time": 180.0,
                    "forces.gas_responsiveness_factor": 5.0,
                    "forces.gas_responsiveness_range": 0.05}[k]

    q = 800.0
    for _ in range(2000):
        q += gas_nudge(q, 0.0, 1000.0, T())
    assert q == pytest.approx(0.0, abs=1e-6)


def test_le_vaisseau_converge_vers_son_altitude_d_equilibre(cargo):
    """« Est-ce que ca decolle, et a quelle altitude ca se stabilise ? »"""
    sim = Simulation(cargo, SimOptions(altitude=63.0, initial_gas="vide"))
    sim.run(6000)

    assert abs(sim.state.vertical_speed) < 0.01, "la montee doit s'arreter"
    poids = sim.mass.total * sim.tables.get("pressure.gravity")
    portance = sum(f.vector[1] for f in sim.current_forces() if f.vector[1] > 0)
    assert portance == pytest.approx(poids, rel=1e-3), "portance = poids a l'equilibre"
    assert sim.state.altitude > 63.0, "ce vaisseau doit monter"


def test_la_pression_est_recalculee_a_chaque_tick(sim):
    sim.run(50)
    haute = sim.state.pressure
    sim.state.position[1] += 200.0
    sim.step()
    assert sim.state.pressure < haute


def test_les_forces_portent_leur_point_d_application(sim):
    familles = {f.family for f in sim.current_forces()}
    assert "gravite" in familles
    assert "ballon" in familles
    assert "trainee" in familles
    for f in sim.current_forces():
        assert len(f.vector) == 3 and len(f.point) == 3
        assert f.label


def test_le_couple_net_ecarte_le_poids(sim):
    """Le poids s'applique au centre de masse : il ne produit aucun moment."""
    from createsim.sim.forces import torque_about
    forces = sim.current_forces()
    com = sim.mass.com
    avec = torque_about(forces, com, skip=())
    sans = torque_about(forces, com)
    assert avec == pytest.approx(sans, abs=1e-6)


def test_le_sol_porte_le_bas_de_coque_et_pas_le_centre_de_masse(cargo):
    """Le vaisseau part a vide, tombe, SE POSE, puis redecolle une fois rempli.

    Ce qui est verifie ici, c'est sur quoi le vaisseau repose. Le plancher
    d'avant portait le centre de masse, avec l'hypothese tacite que le bas de
    coque se trouvait a la cote 0 de la structure. Le cargo commence a y = 3 :
    il s'enterrait donc de trois blocs.
    """
    sim = Simulation(cargo, SimOptions(altitude=60.0, initial_gas="vide",
                                       ground_enabled=True, ground_altitude=10.0))
    coque = cargo.organ("coque")
    assert coque.lowest_local() == pytest.approx(3.0), (
        "le cargo ne commence pas a la cote 0 — c'est tout l'interet du test")

    assert sim.lowest_point() > 10.0, "le depart doit etre au-dessus du sol"
    pose = False
    creux = float("inf")
    for _ in range(400):
        sim.step()
        bas = sim.lowest_point()
        creux = min(creux, bas)
        pose = pose or sim.state.on_ground
        assert bas >= 10.0 - 1e-6, "le sol a ete traverse"
    assert pose, "le vaisseau a vide aurait du toucher le sol"
    assert creux == pytest.approx(10.0, abs=1e-3), "il doit toucher, pas friser"
    assert sim.lowest_point() > 10.5, "il doit redecoller une fois rempli"


def test_un_vaisseau_pose_se_stabilise_sur_ses_appuis(cachalot_model):
    """« Poser le vaisseau » : il tombe, touche, bascule sur son polygone de
    sustentation et s'arrete — au lieu de rester fige dans l'assiette qu'il
    avait en l'air, ou de tournoyer parce que rien ne s'oppose au couple.

    La reaction du sol vaut exactement ce qu'il faut pour annuler la resultante
    descendante, et elle s'applique au barycentre des appuis : le couple qui en
    sort est celui du poids autour de ces appuis.
    """
    sim = Simulation(cachalot_model,
                     SimOptions(altitude=40.0, initial_gas="vide",
                                ground_enabled=True, ground_altitude=0.0))
    sim.run(1200)

    assert sim.state.on_ground
    assert sim.lowest_point() == pytest.approx(0.0, abs=0.2)
    # au repos : plus de vitesse, plus de rotation
    assert abs(sim.state.velocity[1]) < 1e-2
    assert max(abs(v) for v in sim.state.angular_velocity) < 0.05
    assert abs(sim.report()["attitude"]["tangage"]) < 15.0
    assert abs(sim.report()["attitude"]["roulis"]) < 15.0

    # et il ne repart pas tout seul
    avant = sim.lowest_point()
    sim.run(1200)
    assert sim.lowest_point() == pytest.approx(avant, abs=0.2)


def test_la_reaction_du_sol_reprend_exactement_la_descente(cachalot_model):
    """Ni plus — le vaisseau rebondirait — ni moins — il s'enfoncerait."""
    sim = Simulation(cachalot_model,
                     SimOptions(altitude=40.0, initial_gas="vide",
                                ground_enabled=True, ground_altitude=0.0))
    sim.run(1200)

    contacts = [f for f in sim.state.forces if f.family == "contact"]
    assert contacts, "un vaisseau pose doit montrer son appui"
    reste = sum(f.vector[1] for f in sim.state.forces if f.family != "contact")
    porte = sum(f.vector[1] for f in contacts)
    assert porte == pytest.approx(-reste, rel=1e-9)


def test_la_trace_est_exploitable(sim, tmp_path):
    trace = Trace()
    sim.run(100, trace)
    assert len(trace) == 101
    chemin = trace.to_csv(str(tmp_path / "trace.csv"))
    lignes = open(chemin, encoding="utf-8").read().splitlines()
    colonnes = lignes[0].split(",")
    # les colonnes de base d'abord, puis une par force et par axe
    assert colonnes[:len(BASE_COLUMNS)] == list(BASE_COLUMNS)
    assert any(c.startswith("f_") for c in colonnes)
    assert len(lignes) == 102
    assert all(math.isfinite(v) for v in trace.column("y"))


def test_tenir_vingt_ticks_par_seconde(sim):
    """NF1 : le seuil obligatoire du cahier."""
    sim.run(20)                      # chauffe
    depart = time.perf_counter()
    sim.run(400)
    ecoule = time.perf_counter() - depart
    cadence = 400 / ecoule
    assert cadence >= 20.0, "%.0f ticks/s seulement" % cadence
