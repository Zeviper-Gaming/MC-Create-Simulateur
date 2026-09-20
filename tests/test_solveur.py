"""Non-regression du solveur cinetique.

Chacun de ces tests correspond a un mecanisme que le solveur ignorait, et que
la confrontation aux regimes enregistres a revele. La concordance sur la flotte
est passee de 30/131 a 124/131 en les ajoutant.

Les vaisseaux trop lourds pour le depot sont references par leur chemin et le
test se saute s'ils sont absents : ils vivent dans l'instance CurseForge.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from createsim.data.nbt import axis_of
from createsim.model.vehicle import VehicleModel
from createsim.sim.kinetics import concordance, solve_speeds

from conftest import FIXTURES

SCHEMATICS = Path(
    r"C:/Users/Florian/curseforge/minecraft/Instances/La Bonne Compagnie/schematics")
DOWNLOADS = Path(r"C:/Users/Florian/Downloads")


def _solve(model):
    rs = model.organ("redstone")
    signals = rs.signals({lv.pos: lv.initial for lv in rs.levers})
    return solve_speeds(model.organ("cinetique"), signals)


def _external(path: Path, tables):
    if not path.is_file():
        pytest.skip("vaisseau hors depot : %s" % path.name)
    return VehicleModel.load(str(path), tables)


@pytest.fixture
def cachalot(tables):
    return VehicleModel.load(str(FIXTURES / "cachalot_volant_v3.nbt"), tables)


# --- derivation de l'axe de rotation ---------------------------------------
def test_axe_derive_de_facing_et_axis_along_first():
    """Create DirectionalAxisKineticBlock : sur une jauge, `facing` designe la
    face d'affichage, pas l'axe. Le confondre coupait la transmission net."""
    jauge = {"props": {"facing": "west", "axis_along_first": "true"}}
    assert axis_of(jauge) == "y"
    jauge["props"]["axis_along_first"] = "false"
    assert axis_of(jauge) == "z"
    # sans `axis_along_first`, `facing` EST l'axe (palier d'helice)
    assert axis_of({"props": {"facing": "west"}}) == "x"
    # `axis` explicite prime toujours
    assert axis_of({"props": {"axis": "z", "facing": "west"}}) == "z"


def test_une_jauge_ne_coupe_plus_la_transmission(cachalot):
    """Un manometre sur l'arbre du moulin arretait la propagation a 16 noeuds.

    Le critere porte sur les jauges que le JEU enregistre en rotation : celles
    qui sont a l'arret dans le NBT doivent le rester.
    """
    kin = cachalot.organ("cinetique")
    solution = _solve(cachalot)
    jauges = [p for p, b in kin.nodes.items()
              if b["name"] in ("create:stressometer", "create:speedometer")]
    assert jauges, "ce vaisseau porte des jauges"
    tournantes = [p for p in jauges if p in kin.recorded]
    assert tournantes, "au moins une jauge tourne dans le fichier"
    for p in tournantes:
        assert p in solution.speeds, "jauge en rotation non atteinte : %s" % (p,)
        assert abs(abs(solution.speeds[p]) - abs(kin.recorded[p])) < 0.51


# --- contraption assemblee --------------------------------------------------
def test_un_rotor_assemble_est_signale_et_non_compte_a_zero(cachalot):
    """`Running: 1` : les blocs du rotor ne sont plus dans le fichier.

    Annoncer zero voile serait un mensonge ; le jeu fournit `LastGenerated`.
    """
    paliers = cachalot.organ("paliers")
    assembles = [b for b in paliers.bearings if b.assembled]
    assert assembles, "ce vaisseau a ete sauvegarde contraptions assemblees"
    for b in assembles:
        assert b.sails_known is False
        assert b.report()["voiles"] is None
        assert "pas defaut du vaisseau" in b.report()["fiabilite"]


def test_le_moulin_assemble_reprend_le_regime_du_jeu(cachalot):
    kin = cachalot.organ("cinetique")
    moulins = [s for s in kin.sources if s.block == "create:windmill_bearing"]
    assert len(moulins) == 1
    assert moulins[0].kind == "mesure_du_jeu"
    assert moulins[0].rpm == pytest.approx(16.0)


def test_concordance_complete_sur_le_cachalot(cachalot):
    """53 regimes enregistres, tous retrouves. C'etait 0/53."""
    result = concordance(cachalot.organ("cinetique"), _solve(cachalot).speeds)
    assert result["concordance_solveur"] == "53/53", result["ecarts"]


# --- transmission analogique ------------------------------------------------
def test_le_rapport_ne_s_applique_qu_entre_arbre_et_roue(cachalot):
    """Le bloc siege a la vitesse de son ARBRE ; sa roue dentee integree tourne
    a (15 - signal)/16 de celle-ci.

    Appliquer le rapport a chaque arrivee sur le bloc faisait s'emballer toute
    boucle qui repassait par la transmission, jusqu'au plafond de 256 tr/min.
    """
    kin = cachalot.organ("cinetique")
    cotes = set(kin.transmission_sides.values())
    assert cotes <= {"arbre_vers_roue", "roue_vers_arbre"}
    assert cotes, "ce vaisseau porte des transmissions analogiques"


def test_aucun_emballement_jusqu_au_plafond(cachalot, tables):
    """Un regime calcule a exactement 256 sans qu'il soit mesure trahit une
    boucle multiplicative, pas une vraie saturation."""
    kin = cachalot.organ("cinetique")
    speeds = _solve(cachalot).speeds
    plafond = tables.get("kinetics.max_rotation_speed")
    for pos, v in speeds.items():
        if abs(v) < plafond - 1e-9:
            continue
        mesure = kin.recorded.get(pos)
        assert mesure is not None and abs(abs(mesure) - plafond) < 0.51, (
            "regime au plafond en %s sans mesure correspondante" % (pos,))


def test_le_signal_quinze_decouple_la_roue_pas_l_arbre(cachalot):
    """Signal 15 : la roue dentee se detache, mais l'arbre continue de passer.

    Couper les deux ferait disparaitre tout un aval du bilan.
    """
    kin = cachalot.organ("cinetique")
    decouples = [p for p, b in kin.nodes.items()
                 if b["name"] == "simulated:analog_transmission"
                 and int((b.get("nbt") or {}).get("Signal", 0)) >= 15]
    assert decouples, "ce vaisseau porte des transmissions decouplees"
    speeds = _solve(cachalot).speeds
    assert any(p in speeds for p in decouples), (
        "une transmission decouplee garde sa vitesse d'arbre")


# --- mecanismes valides sur des vaisseaux hors depot ------------------------
def test_moteur_surchauffe_double_sa_sortie(tables):
    """L'etage x2 que le cahier signalait comme non modelise.

    `GeneratedSpeed` vaut 32 partout ; seul `SuperHeated` distingue les 64.
    """
    model = _external(DOWNLOADS / "dirt_bike_by_smokeyblade.nbt", tables)
    moteurs = [s for s in model.organ("cinetique").sources
               if s.block.endswith("_portable_engine")]
    assert moteurs
    assert all(s.rpm == pytest.approx(64.0) for s in moteurs), (
        [s.rpm for s in moteurs])


def test_moteur_non_surchauffe_reste_a_trente_deux(sim):
    moteurs = [s for s in sim.kin.sources if s.block.endswith("_portable_engine")]
    assert moteurs, "cargo_airship porte des moteurs portables"
    assert all(s.rpm == pytest.approx(32.0) for s in moteurs)


def test_moteur_creatif_et_chaines_sur_le_cruiser(tables):
    """Le cas que le cahier donnait a 0/18 : source inconnue et 147 blocs de
    chaine hors reseau."""
    model = _external(SCHEMATICS / "c1_air_cruiser.nbt", tables)
    kin = model.organ("cinetique")
    moteurs = [s for s in kin.sources if s.block == "create:creative_motor"]
    assert len(moteurs) == 1
    assert moteurs[0].rpm == pytest.approx(16.0)
    assert moteurs[0].kind == "reglage"

    chaines = [p for p, b in kin.nodes.items()
               if b["name"] == "create:encased_chain_drive"]
    assert len(chaines) > 100
    speeds = _solve(model).speeds
    assert sum(1 for p in chaines if p in speeds) > 0

    result = concordance(kin, speeds)
    assert result["concordance_solveur"] == "18/18", result["ecarts"]


def test_un_embrayage_alimente_coupe(cachalot):
    """Sans cela le solveur entraine un arbre que le jeu laisse a l'arret."""
    kin = cachalot.organ("cinetique")
    embrayages = [(p, b) for p, b in kin.nodes.items()
                  if b["name"] == "create:clutch"]
    for pos, block in embrayages:
        if block["props"].get("powered") == "true":
            assert not kin.adj.get(pos), "un embrayage alimente ne propage rien"
