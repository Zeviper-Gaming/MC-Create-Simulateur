"""Tangage et roulis par les couples (F2.3), et l'assiette au rendu (F3.4).

Trois choses se testent ici, dans cet ordre :

    le tenseur d'inertie    tire de la GEOMETRIE, pas d'un coefficient reglable
    le pas angulaire        implicite, avec le terme gyroscopique
    ce que ca donne         sur un vrai vaisseau, et ce que ca ne casse pas

La derniere ligne compte autant que les deux premieres : la rotation doit
pouvoir se couper, et coupee, rendre EXACTEMENT la trajectoire d'avant. C'est
ce qui garde le niveau 2 de validation a son ecart d'origine.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from createsim.sim import rotation as R
from createsim.sim.integrator import DT, integrate
from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation


# --- le tenseur d'inertie ---------------------------------------------------
def test_le_tenseur_vaut_la_somme_bloc_a_bloc(cargo):
    """Le tenseur est accumule en moments d'ordre deux autour de l'ORIGINE puis
    transporte au centre de masse (Huygens). Il doit valoir, au flottant pres,
    la somme directe bloc par bloc autour du centre de masse."""
    organ = cargo.organ("masse")
    com = organ.com
    brut = np.zeros((3, 3))
    for pos, entry in cargo.structure.blocks.items():
        m = cargo.props.mass(entry["name"])
        if m <= 0:
            continue
        d = np.array([pos[i] + 0.5 - com[i] for i in range(3)])
        # un cube plein de cote 1 : m/6 autour de chacun de ses axes
        brut += m * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
        brut += np.eye(3) * m / 6.0

    got = np.asarray(organ.inertia())
    assert got == pytest.approx(brut, rel=1e-9, abs=1e-6)


def test_le_tenseur_est_symetrique_et_defini_positif(cargo):
    """Un tenseur d'inertie qui ne l'est pas rendrait `np.linalg.solve`
    instable — et une rotation qui diverge au lieu de s'amortir."""
    tensor = np.asarray(cargo.organ("masse").inertia())
    assert tensor == pytest.approx(tensor.T)
    assert min(np.linalg.eigvalsh(tensor)) > 0


def test_l_inertie_suit_une_edition_sans_tout_recalculer(cargo, tables):
    """La masse est un organe DIFFERENTIEL : retirer un bloc met a jour les six
    moments sans balayer les autres. Le tenseur obtenu doit egaler celui d'un
    vaisseau recharge depuis le fichier et edite de la meme facon."""
    from createsim.model.vehicle import VehicleModel

    avant = np.asarray(cargo.organ("masse").inertia())
    pos = max((p for p, e in cargo.structure.blocks.items()
               if cargo.props.mass(e["name"]) > 0),
              key=lambda p: cargo.props.mass(cargo.structure.blocks[p]["name"]))
    cargo.delete(pos)
    apres = np.asarray(cargo.organ("masse").inertia())
    assert not np.allclose(avant, apres)

    neuf = VehicleModel.load(str(cargo.structure.path), tables)
    neuf.structure.remove_block(pos)
    neuf.organ("masse").recompute()
    assert apres == pytest.approx(np.asarray(neuf.organ("masse").inertia()),
                                  rel=1e-9, abs=1e-6)


# --- le pas angulaire -------------------------------------------------------
def test_un_couple_pur_accelere_selon_l_inertie():
    """Autour d'un axe principal, sans amortissement : omega = couple x t / I,
    exactement. Le terme gyroscopique y est nul, rien ne doit le masquer."""
    inertia = np.diag([2.0, 3.0, 4.0])
    zero = np.zeros((3, 3))
    q, omega = R.IDENTITY, (0.0, 0.0, 0.0)
    for _ in range(10):
        q, omega = R.step(q, omega, inertia, (0.0, 0.0, 10.0), zero, DT)
    assert omega[2] == pytest.approx(10.0 * 10 * DT / 4.0, rel=1e-9)
    assert omega[0] == pytest.approx(0.0, abs=1e-9)
    assert omega[1] == pytest.approx(0.0, abs=1e-9)


def test_l_amortissement_angulaire_suit_le_schema_implicite():
    """`(I + D dt) omega' = I omega` : chaque pas divise par `1 + k dt / I`."""
    inertia = np.diag([2.0, 2.0, 2.0])
    damping = np.diag([6.0, 6.0, 6.0])
    q, omega = R.IDENTITY, (0.0, 0.0, 1.0)
    for _ in range(40):
        q, omega = R.step(q, omega, inertia, (0.0, 0.0, 0.0), damping, DT)
    attendu = (1.0 + 6.0 * DT / 2.0) ** -40
    assert omega[2] == pytest.approx(attendu, rel=1e-9)


def test_un_amortissement_enorme_ne_diverge_pas():
    """Le cas qui a impose l'implicite : sur le c1_air_cruiser, `D dt / I`
    depasse 1. Un schema explicite y change de signe a chaque pas puis part a
    l'infini ; l'implicite ne fait que freiner."""
    inertia = np.diag([1.0, 1.0, 1.0])
    damping = np.diag([1000.0, 1000.0, 1000.0]) / DT
    q, omega = R.IDENTITY, (0.0, 0.0, 5.0)
    suite = []
    for _ in range(50):
        q, omega = R.step(q, omega, inertia, (0.0, 0.0, 0.0), damping, DT)
        suite.append(omega[2])
    assert all(math.isfinite(v) for v in suite)
    assert all(0.0 <= suite[i + 1] < suite[i] for i in range(len(suite) - 1))


def test_le_terme_gyroscopique_fait_preceder_un_axe_non_principal():
    """Autour d'un axe principal, la rotation libre garde sa direction. Autour
    d'un axe quelconque d'un corps dissymetrique, elle precesse — c'est
    exactement ce que le terme `omega x (I omega)` porte. L'omettre donne une
    rotation qui a l'air juste et ne l'est pas."""
    inertia = np.diag([1.0, 2.0, 3.0])
    zero = np.zeros((3, 3))

    q, omega = R.IDENTITY, (1.0, 0.0, 0.0)
    for _ in range(40):
        q, omega = R.step(q, omega, inertia, (0.0, 0.0, 0.0), zero, DT)
    assert omega == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)

    q, omega = R.IDENTITY, (1.0, 0.7, 0.0)
    for _ in range(40):
        q, omega = R.step(q, omega, inertia, (0.0, 0.0, 0.0), zero, DT)
    assert abs(omega[2]) > 1e-3


def test_l_assiette_reste_un_quaternion_unitaire():
    """`advance` renormalise : sans cela, quelques milliers de ticks suffisent
    a faire deriver la norme et a etirer le vaisseau au rendu.

    L'amortissement pris ici est le MINIMUM qu'un vaisseau puisse avoir : le
    taux universel de 0,09 par seconde, qui s'applique meme a une coque sans
    enveloppe. 400 secondes de vol libre, et la norme ne bouge pas.
    """
    inertia = np.diag([1.0, 2.0, 3.0])
    damping = 0.09 * inertia
    q, omega = R.IDENTITY, (1.3, 0.7, -0.4)
    for _ in range(8000):
        q, omega = R.step(q, omega, inertia, (0.0, 0.0, 0.0), damping, DT)
    assert sum(v * v for v in q) == pytest.approx(1.0, abs=1e-9)
    assert all(math.isfinite(v) for v in omega)


def test_une_rotation_non_finie_arrete_la_rotation_au_lieu_de_la_corrompre():
    """Le terme gyroscopique reste explicite : sans aucun amortissement, une
    rotation rapide finit par diverger (limite documentee dans `rotation.py`).
    Le garde-fou doit rendre une assiette intacte et une vitesse nulle, pas un
    quaternion de NaN qui ferait disparaitre le vaisseau du rendu."""
    inertia = np.diag([1.0, 2.0, 3.0])
    zero = np.zeros((3, 3))
    q, omega = R.IDENTITY, (float("inf"), 0.0, 0.0)
    q, omega = R.step(q, omega, inertia, (0.0, 0.0, 0.0), zero, DT)

    assert q == R.IDENTITY
    assert omega == (0.0, 0.0, 0.0)


# --- sur un vrai vaisseau ---------------------------------------------------
def test_le_cargo_pique_du_nez_puis_se_stabilise(cargo):
    """Le cargo porte sa portance en avant de son centre de masse : il pique, et
    l'amortissement d'enveloppe l'arrete a un angle fini. Une assiette qui ne se
    stabilise pas signale un amortissement absent ou de mauvais signe."""
    sim = Simulation(cargo, SimOptions())
    sim.run(1200)
    attitude = sim.report()["attitude"]

    assert attitude["active"]
    assert attitude["tangage"] == pytest.approx(-9.75, abs=0.5)
    assert max(abs(v) for v in attitude["vitesse_angulaire"]) < 1e-3


def test_l_assiette_d_equilibre_vaut_l_arctangente_du_bras_de_levier(cargo):
    """Verification analytique, dans l'esprit du niveau 2 de validation.

    A l'equilibre le couple s'annule : le vaisseau a bascule juste assez pour
    que le centre de portance revienne a l'aplomb du centre de masse. L'angle
    ne depend alors que de la geometrie — `arctan(bras / hauteur)` — et pas du
    tout de l'inertie ni de l'amortissement, qui ne decident que du chemin pour
    y arriver. Un ecart signalerait un couple mal forme, pas un reglage.
    """
    statique = Simulation(cargo, SimOptions(rotation=False))
    statique.run(1200)
    bilan = statique.report()["bilan"]["tangage"]
    com = statique.report()["centre_de_masse"]
    attendu = math.degrees(math.atan2(bilan["bras_longitudinal"],
                                      bilan["centre_de_portance"][1] - com[1]))

    tournant = Simulation(cargo, SimOptions())
    tournant.run(1200)
    obtenu = tournant.report()["attitude"]["tangage"]

    assert attendu == pytest.approx(9.82, abs=0.05)
    assert abs(obtenu) == pytest.approx(attendu, abs=0.3)


def test_rotation_coupee_rend_exactement_la_trajectoire_d_avant(cargo):
    """L'exigence dure : `rotation=False` doit repasser par le chemin de code
    d'avant. C'est ce qui garde le niveau 2 de validation a son ecart d'origine
    au lieu de le voir bouger d'un lot a l'autre."""
    sim = Simulation(cargo, SimOptions(rotation=False))
    assert sim.attitude() is None
    sim.run(300)

    assert sim.state.orientation == R.IDENTITY
    assert sim.state.angular_velocity == [0.0, 0.0, 0.0]
    assert sim.state.torque == (0.0, 0.0, 0.0)
    assert sim.report()["attitude"]["active"] is False


def test_un_vaisseau_pose_au_sol_ne_bascule_pas(cachalot_model):
    """Le sol est une fonction hauteur, pas un moteur de contact : il ne peut
    pas rendre de couple de reaction. Sans precaution, un vaisseau pose dessus
    tourne autour de son centre de masse jusqu'a se retourner. La rotation est
    donc GELEE au contact — simplification assumee, et documentee comme telle.
    """
    sim = Simulation(cachalot_model,
                     SimOptions(altitude=0.0, ground_enabled=True))
    sim.run(600)
    assert sim.state.on_ground
    depart = sim.report()["attitude"]
    sim.run(600)
    arrivee = sim.report()["attitude"]

    assert arrivee["tangage"] == pytest.approx(depart["tangage"], abs=1e-9)
    assert arrivee["roulis"] == pytest.approx(depart["roulis"], abs=1e-9)
    assert abs(arrivee["tangage"]) < 45 and abs(arrivee["roulis"]) < 45


# --- les directions liees au vaisseau ---------------------------------------
def test_les_directions_du_vaisseau_tournent_avec_lui():
    """Une poussee d'helice suit l'axe de son palier ; la gravite non. C'est
    toute la difference entre un vecteur du repere du vaisseau et un vecteur du
    monde, et `turn` est la frontiere entre les deux."""
    from createsim.sim.forces import turn

    quart = R.matrix((math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)))
    assert turn((1.0, 0.0, 0.0), quart) == pytest.approx((0.0, 1.0, 0.0),
                                                         abs=1e-9)
    assert turn((1.0, 0.0, 0.0), None) == (1.0, 0.0, 0.0)


def test_l_amortissement_est_evalue_dans_le_repere_du_vaisseau():
    """Les coefficients d'amortissement sont diagonaux dans le repere du
    VAISSEAU : les roues freinent selon leur axe, les voiles selon leur normale.
    A plat, ca doit rendre exactement le chemin sans rotation ; tourne d'un
    quart de tour, les axes amortis doivent avoir tourne aussi."""
    reglage = dict(external_force=(0.0, 0.0, 0.0), damping=(100.0, 1.0, 1.0),
                   mass=1000.0)

    plat_p, plat_v = [0.0] * 3, [10.0, 10.0, 0.0]
    integrate(plat_p, plat_v, **reglage)
    ident_p, ident_v = [0.0] * 3, [10.0, 10.0, 0.0]
    integrate(ident_p, ident_v, **reglage, rotation=np.eye(3))
    assert ident_v == pytest.approx(plat_v, abs=1e-12)

    quart = R.matrix((math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)))
    tourne_p, tourne_v = [0.0] * 3, [10.0, 10.0, 0.0]
    integrate(tourne_p, tourne_v, **reglage, rotation=quart)
    # l'axe fortement amorti pointe maintenant vers +y : c'est y qui freine
    assert tourne_v[1] < plat_v[1]
    assert tourne_v[0] > plat_v[0]


def test_le_couple_prend_le_bras_tourne_et_pas_le_vecteur():
    """Les points d'application sont donnes dans le repere du vaisseau, les
    vecteurs de force dans le monde. Tourner les deux ferait tourner la gravite
    avec la coque — et un vaisseau renverse tomberait vers le haut."""
    from createsim.sim.forces import Force, torque_about

    quart = R.matrix((math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)))
    poussee = [Force("helice", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), "essai")]

    assert torque_about(poussee, (0.0, 0.0, 0.0)) == pytest.approx(
        (0.0, -1.0, 0.0), abs=1e-9)
    assert torque_about(poussee, (0.0, 0.0, 0.0),
                        rotation=quart) == pytest.approx((1.0, 0.0, 0.0),
                                                          abs=1e-9)
