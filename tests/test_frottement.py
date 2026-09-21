"""Les modeles de frottement, releves au bytecode de Create/Sable/Offroad.

Ce fichier fige ce que la lecture des jars a etabli, formule par formule. Ce
n'est pas de la paraphrase de documentation : chaque assertion correspond a un
offset de bytecode cite dans `docs/rapport-frottement-create.md`.

Les quatre mecanismes en jeu, et ce qui les distingue :

    trainee d'enveloppe   0,33 par bloc etanche, x pression, isotrope
    amortissement universel  un TAUX par seconde du corps rigide, x masse
    roues                 traction, freinage et derive, anisotropes
    voiles                portance perpendiculaire + deux trainees
    levitite              anisotrope et dependant de la vitesse
"""
from __future__ import annotations

import math

import pytest

from createsim.sim import forces as F
from createsim.sim.integrator import DT, integrate
from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation


# --- l'amortissement universel ---------------------------------------------
def test_l_amortissement_universel_passe_par_la_masse(cargo, tables):
    """`Rapier3D.initialize(gx, gy, gz, drag)` : c'est un TAUX par seconde
    applique au corps entier, pas une trainee par bloc. Pour le ramener a un
    coefficient de force il faut la masse."""
    drag = cargo.organ("trainee")
    masse = cargo.organ("masse").total
    taux = tables.get("pressure.universal_drag")

    assert drag.universal_coefficient(masse) == pytest.approx(taux * masse)
    assert drag.coefficient(1.0, masse) == pytest.approx(
        drag.envelope_coefficient(1.0) + taux * masse)


def test_seul_l_amortissement_universel_impose_onze_secondes(tables):
    """Un corps sans bloc etanche n'accelere plus indefiniment : le taux seul
    fixe tau = 1/0,09 = 11,1 s."""
    taux = tables.get("pressure.universal_drag")
    assert 1.0 / taux == pytest.approx(11.11, abs=0.01)

    masse = 1000.0
    position, velocity = [0.0, 0.0, 0.0], [10.0, 0.0, 0.0]
    for _ in range(int(11.11 / DT)):
        integrate(position, velocity, (0.0, 0.0, 0.0), taux * masse, masse)
    assert velocity[0] == pytest.approx(10.0 / math.e, rel=0.01)


def test_il_pese_surtout_sur_un_vaisseau_massif_et_peu_etanche(cruiser_model):
    """Le c1_air_cruiser porte 20 659 blocs pour 839 etanches : c'est la que le
    terme manquant divisait la constante de temps par plus de six."""
    drag = cruiser_model.organ("trainee")
    masse = cruiser_model.organ("masse").total
    avant = masse / drag.envelope_coefficient(1.0)
    apres = masse / drag.coefficient(1.0, masse)
    assert avant / apres > 6.0, "%.1f s -> %.1f s" % (avant, apres)
    assert apres < 1.0 / 0.09, "l'amortissement universel est le plafond"


# --- fudgeFriction ----------------------------------------------------------
def test_la_glace_laisse_de_l_adherence(tables):
    """`fudgeFriction` n'est PAS `min(f, 1)` : f < 1 ? 0,1 + 0,9 f : f.

    Un vehicule sur la glace avance encore. Le confondre avec un clamp le
    laissait totalement impuissant.
    """
    assert F.fudge_friction(0.0, tables) == pytest.approx(0.10)
    assert F.fudge_friction(0.05, tables) == pytest.approx(0.145)   # meule
    assert F.fudge_friction(0.25, tables) == pytest.approx(0.325)   # boue
    assert F.fudge_friction(1.0, tables) == pytest.approx(1.0)


def test_un_frottement_superieur_a_un_passe_inchange(tables):
    """Sable des ames, miel, tapis roulant : 1,65, et le remappage n'y touche
    pas — c'est ce qui donne a la derive laterale son adherence superieure."""
    assert F.fudge_friction(1.65, tables) == pytest.approx(1.65)
    grip, surface = F.wheel_grip(1.65, tables)
    assert grip == pytest.approx(1.65), "la derive laterale n'est pas bornee"
    assert surface == pytest.approx(1.0), "traction et freinage saturent a 1"


# --- la traction des roues --------------------------------------------------
def test_le_frein_a_fond_immobilise_la_roue(tables):
    """LE bug que la relecture du bytecode a leve : `frein = signal / 15`, brut.

    Le code fabriquait son frein avec 0,075 et 0,3 — les constantes du freinage
    DYNAMIQUE — et une roue freinee a fond tractait encore a 62 %.
    """
    coef = tables.get("forces.wheel_traction_coef")
    attendu = {0: 1.750, 5: 1.1667, 10: 0.5833, 15: 0.0}
    for signal, valeur in attendu.items():
        brake = F.wheel_brake((0, 0, 0), {"SignalStrength": signal}, {})
        traction = 1.0 * (1.0 - brake) * 1.0 * coef
        assert traction == pytest.approx(valeur, abs=1e-3), "signal %d" % signal


def test_le_frein_se_lit_au_dessus_et_le_levier_y_arrive(tables):
    """Le signal vient du bloc AU-DESSUS du support ; un levier doit pouvoir
    le piloter, donc `signals` prime sur la valeur figee du NBT."""
    pos = (4, 2, 7)
    assert F.wheel_brake(pos, {"SignalStrength": 0}, {pos: 15}) == 1.0
    assert F.wheel_brake(pos, {"SignalStrength": 15}, {pos: 0}) == 0.0


# --- le frottement dynamique ------------------------------------------------
def test_la_deceleration_est_independante_de_la_masse_sous_saturation(tables):
    """`strengthMul = 20 x min(masse_portee, raideur)`. Sous saturation il vaut
    20 x masse, et la deceleration ne depend plus de la masse — comme le
    frottement reel."""
    facteur = tables.get("forces.wheel_strength_mul_factor")
    base = tables.get("forces.wheel_brake_base")
    for masse in (200.0, 800.0, 2000.0):
        raideur = masse * 2                     # jamais sature
        strength_mul = facteur * min(masse, raideur)
        taux = base * 1.0 * strength_mul / masse
        assert taux == pytest.approx(facteur * base), "masse %.0f" % masse
    assert 1.0 / (facteur * base) == pytest.approx(0.667, abs=0.01)


def test_une_suspension_molle_sature_et_freine_moins(tables):
    """Au-dela de la raideur, `strengthMul` plafonne : un vehicule surcharge
    sur suspension molle ne freine plus."""
    facteur = tables.get("forces.wheel_strength_mul_factor")
    raideur = 256.0
    leger = facteur * min(200.0, raideur) / 200.0
    lourd = facteur * min(2000.0, raideur) / 2000.0
    assert lourd < leger / 5.0, "la saturation doit se payer"


def test_freinage_et_derive_sont_par_seconde(tables):
    """Le moteur multiplie tout par `dt` et applique une impulsion : les
    coefficients sont par seconde. C'est ce qui fixe 0,67 s frein relache et
    0,13 s frein a fond — pas 20 fois moins."""
    base = tables.get("forces.wheel_brake_base")
    step = tables.get("forces.wheel_brake_per_signal")
    facteur = tables.get("forces.wheel_strength_mul_factor")
    relache = 1.0 / (facteur * base)
    a_fond = 1.0 / (facteur * (base + step))
    assert relache == pytest.approx(0.667, abs=0.01)
    assert a_fond == pytest.approx(0.133, abs=0.01)


# --- l'amortissement par axe ------------------------------------------------
def test_un_amortissement_scalaire_reste_accepte():
    """Les trois axes egaux doivent redonner exactement l'ancien comportement."""
    a = ([0.0, 0.0, 0.0], [5.0, -2.0, 1.0])
    b = ([0.0, 0.0, 0.0], [5.0, -2.0, 1.0])
    for _ in range(50):
        integrate(a[0], a[1], (10.0, 0.0, 0.0), 40.0, 100.0)
        integrate(b[0], b[1], (10.0, 0.0, 0.0), (40.0, 40.0, 40.0), 100.0)
    assert a[1] == pytest.approx(b[1])
    assert a[0] == pytest.approx(b[0])


def test_un_axe_sans_amortissement_garde_son_acceleration_pure():
    position, velocity = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    for _ in range(20):
        integrate(position, velocity, (100.0, 100.0, 0.0),
                  (0.0, 50.0, 0.0), 100.0)
    assert velocity[0] == pytest.approx(20 * 1.0 * DT, rel=1e-9)
    assert velocity[1] < velocity[0], "l'axe amorti doit rester en arriere"


# --- les voiles sont des ailes ----------------------------------------------
def test_les_voiles_de_coque_du_cargo_trainent_sans_porter(cargo, tables):
    """Les 44 voiles de coque du cargo sont SYMETRIQUES : « Unlike Regular
    Sails, Symmetric Sails only produce Drag ». Elles freinent selon leur axe
    et ne portent rien."""
    sim = Simulation(cargo, SimOptions())
    assert sim.sails.count == 44
    assert all(s.symmetric for s in sim.sails.sails)
    assert F.sail_forces(sim.sails, (10.0, 0.0, 0.0), 1.0, tables) == []

    damping = F.sail_damping(sim.sails, 1.0, tables)
    parallele = 1.75 * 44
    diffuse = tables.get("forces.sail_directionless_drag_scalar") * 44
    assert damping[0] == pytest.approx(parallele + diffuse), "axis=x"
    assert damping[1] == pytest.approx(diffuse)
    assert damping[2] == pytest.approx(diffuse)


def test_la_normale_d_une_voile_symetrique_vient_de_son_axe():
    """`SymmetricSailBlock.sable$getNormal` : Direction.get(POSITIVE, AXIS).
    Elle n'a pas de facing — lire le facing envoyait sa trainee sur y."""
    from createsim.model.sails import sail_normal
    assert sail_normal({"axis": "x"}, symmetric=True) == "east"
    assert sail_normal({"axis": "z"}, symmetric=True) == "south"
    assert sail_normal({"facing": "north"}, symmetric=False) == "south"


def test_une_voile_create_de_coque_porte(tables):
    """Une voile Create hors rotor porte, perpendiculairement a sa surface et
    proportionnellement a la vitesse."""
    from createsim.model.sails import Sail

    class Organe:
        sails = [Sail((0, 0, 0), "up", symmetric=False)]
        centre = (0.5, 0.5, 0.5)

    immobile = F.sail_forces(Organe, (0.0, 0.0, 0.0), 1.0, tables)
    assert all(f.magnitude == pytest.approx(0.0) for f in immobile)
    lance = F.sail_forces(Organe, (10.0, 0.0, 0.0), 1.0, tables)
    assert lance[0].magnitude == pytest.approx(0.475 * 10.0)
    double = F.sail_forces(Organe, (20.0, 0.0, 0.0), 1.0, tables)
    assert double[0].magnitude == pytest.approx(2 * lance[0].magnitude),         "lineaire en vitesse, pas quadratique"


def test_les_voiles_d_un_rotor_ne_comptent_pas(cachalot_v4_model):
    """Le cachalot v4 porte 174 voiles, toutes sur des rotors : leur vitesse
    n'est pas celle du vaisseau, et leur effet est deja porte par le moulin."""
    sails = cachalot_v4_model.organ("voiles")
    total = sum(1 for _pos, b in cachalot_v4_model.structure
                if "sail" in b["name"])
    assert total > 100
    assert sails.count == 0, "aucune voile de coque sur ce vaisseau"


def test_une_voile_symetrique_ne_porte_pas_mais_traine_plus(tables):
    assert tables.get("forces.symmetric_sail_lift_scalar") == 0.0
    assert (tables.get("forces.symmetric_sail_parallel_drag_scalar")
            > tables.get("forces.sail_parallel_drag_scalar"))


# --- le levitite freine -----------------------------------------------------
def test_le_levitite_freine_surtout_a_basse_vitesse(cruiser_model, tables):
    """Profil complet dans `floating_materials/levitite.json`, ignore jusqu'ici :
    vertical 2,0 lent / 0,1 rapide, x 11 par `scale_friction_with_gravity`."""
    organ = cruiser_model.organ("levitite")
    assert organ.cells, "ce vaisseau porte du levitite"

    repos = F.levitite_damping(organ, (0.0, 0.0, 0.0), tables)
    vite = F.levitite_damping(organ, (0.0, 12.0, 0.0), tables)
    assert repos[1] > 10 * vite[1], "le regime lent domine pres de zero"
    assert repos[1] > repos[0], "le profil est anisotrope : vertical > horizontal"

    n = len(organ.cells) * tables.get("pressure.gravity")
    assert repos[1] == pytest.approx((2.0 + 0.1) * n, rel=1e-6)
    assert vite[1] == pytest.approx(0.1 * n, rel=0.01)


def test_un_vaisseau_sans_levitite_n_en_subit_rien(cargo, tables):
    organ = cargo.organ("levitite")
    assert not organ.cells
    assert F.levitite_damping(organ, (0.0, 5.0, 0.0), tables) == [0.0, 0.0, 0.0]


# --- ce que le rapport doit dire --------------------------------------------
def test_les_simplifications_sont_signalees(cruiser_model):
    """Ni la masse portee par roue ni le melange du levitite ne sont exacts :
    le rapport doit le dire plutot que de livrer un chiffre muet."""
    report = Simulation(cruiser_model, SimOptions()).report()
    codes = {a["code"]: a for a in report["anomalies"]}
    assert "F5.11" in codes
    assert codes["F5.11"]["gravite"] == "limite du modele"


def test_la_trainee_publie_ses_deux_termes(cargo):
    report = Simulation(cargo, SimOptions()).report()["trainee"]
    assert report["coefficient_enveloppe"] > 0
    assert report["coefficient_universel"] > 0
    # chaque terme est arrondi au millieme dans le rapport
    assert report["coefficient"] == pytest.approx(
        report["coefficient_enveloppe"] + report["coefficient_universel"],
        abs=0.01)
    assert len(report["amortissement_par_axe"]) == 3
