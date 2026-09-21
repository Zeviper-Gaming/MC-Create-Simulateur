"""Non-regression du modele, et les disciplines que le cahier impose.

Les valeurs attendues sont celles que le calculateur `/mc-create-engineer`
produit sur les memes fichiers : ce sont elles qui garantissent que le passage
du statique au dynamique n'a rien perdu en route.
"""
from __future__ import annotations

import pytest


# --- parite avec le calculateur statique -----------------------------------
def test_masse_et_centre_de_masse(cargo):
    masse = cargo.organ("masse")
    assert masse.total == pytest.approx(1856.75, abs=0.01)
    assert [round(v, 2) for v in masse.com] == [16.54, 14.44, 31.41]


def test_geometrie_du_ballon(cargo):
    pockets = cargo.organ("ballons").pockets
    assert len(pockets) == 1
    assert pockets[0].capacity == 8926


def test_paliers_et_voiles(cargo):
    helices = cargo.organ("paliers").of_type("aeronautics:propeller_bearing")
    assert len(helices) == 2
    assert sorted(b.sails for b in helices) == [40, 40]


def test_blocs_etanches_et_trainee(cargo):
    drag = cargo.organ("trainee")
    assert drag.count == 2490
    assert drag.envelope_coefficient(1.0) == pytest.approx(0.33 * 2490, abs=1e-9)
    # l'amortissement universel du moteur (Rapier) s'ajoute par la MASSE :
    # c'est un taux par seconde, pas une trainee par bloc.
    assert drag.coefficient(1.0, 1000.0) == pytest.approx(0.33 * 2490 + 90.0,
                                                          abs=1e-9)


def test_bilan_de_vol(sim):
    bilan = sim.report()["bilan"]
    assert bilan["ratio_portance_poids"] == pytest.approx(2.424, abs=0.001)
    assert bilan["vole"] is True
    assert bilan["altitude_equilibre"] == pytest.approx(283.2, abs=0.1)


def test_aucun_bloc_hors_table_sur_cette_reference(cargo):
    assert cargo.organ("masse").unknown_total == 0


# --- redstone ---------------------------------------------------------------
def test_la_topologie_redstone_retrouve_les_signaux_du_jeu(cargo):
    """Meme discipline que la cinetique : on publie le score."""
    result = cargo.organ("redstone").concordance()
    assert result["pilotes"] == 7
    assert result["commandes_resolues"] == "7/7"
    assert result["ecarts"] == []


def test_le_cran_affiche_est_le_signal_emis(cargo):
    """Mesure en jeu (`data/mesures/jeu.json`) : sur une manette `inverted`,
    le cran 0 donne 256 tr/min et le cran 15 arrete l'helice — soit exactement
    le signal que le solveur utilise. Le modele supposait l'inverse.
    """
    inverses = [lv for lv in cargo.organ("redstone").levers if lv.inverted]
    assert inverses, "cette structure porte au moins une manette inversee"
    lv = inverses[0]
    assert lv.initial == 15
    assert lv.displayed_angle(15) == 15
    assert lv.report(15)["signal"] == 15


def test_le_piege_est_le_sens_du_destinataire(cachalot_model):
    """Ce qui renverse l'echelle n'est pas le levier mais la transmission :
    son cote reducteur decouple a 15 et passe en prise directe a 0."""
    levers = cachalot_model.organ("redstone").levers
    moteurs = [lv for lv in levers if lv.scale == "inverse"]
    gaz = [lv for lv in levers if lv.scale == "direct"]
    assert moteurs and gaz, "cette console porte les deux sens cote a cote"
    assert "ARRET" in moteurs[0].report(15)["echelle"]
    assert "piege" in moteurs[0].report(15)
    assert "plein gaz" in gaz[0].report(15)["echelle"]
    assert "piege" not in gaz[0].report(15)


def test_un_levier_atteint_ses_bruleurs(cargo):
    rs = cargo.organ("redstone")
    pilotes = [lv for lv in rs.levers if lv.targets]
    assert pilotes, "aucun levier ne commande quoi que ce soit"
    cibles = {p for lv in pilotes for p in lv.targets}
    assert cibles <= set(rs.consumers)


# --- tracabilite et mode expert --------------------------------------------
def test_chaque_constante_porte_sa_source(tables):
    """Aucune constante ne doit etre ecrite sans sa source."""
    for key, entry in tables.entries.items():
        assert entry.source, "constante sans source : %s" % key
        assert entry.mod, "constante sans mod d'origine : %s" % key


def test_le_manifeste_nomme_les_versions_de_mod(tables):
    mods = tables.manifest["mods"]
    assert mods["create"]["version"] == "6.0.10"
    assert mods["sable"]["version"] == "2.0.5"
    assert "alpha" in tables.manifest["avertissement"]


def test_le_mode_expert_se_coupe_et_restaure(tables):
    origine = tables.get("forces.hot_air_strength")
    with pytest.raises(Exception):
        tables.override("forces.hot_air_strength", 9.0)   # expert eteint

    tables.expert_mode = True
    tables.override("forces.hot_air_strength", 9.0)
    assert tables.get("forces.hot_air_strength") == 9.0
    assert tables.tainted
    assert "MODE EXPERT" in tables.source_of("forces.hot_air_strength")
    assert "avertissement" in tables.provenance()

    tables.expert_mode = False            # le couper restaure, sans redemarrage
    assert tables.get("forces.hot_air_strength") == origine
    assert not tables.tainted
    tables.clear_overrides()


def test_le_rapport_porte_sa_provenance(sim):
    provenance = sim.report()["provenance"]
    assert provenance["mode_expert"] is False
    assert provenance["valeurs_modifiees"] == []
    assert "sable" in provenance["mods"]


# --- diagnostic -------------------------------------------------------------
def test_les_anomalies_distinguent_defaut_et_limite_du_modele(sim):
    codes = {a["code"] for a in sim.report()["anomalies"]}
    assert codes, "aucun diagnostic produit"
    for anomalie in sim.report()["anomalies"]:
        if anomalie["code"] in ("F5.7", "F5.8", "F6.9"):
            assert anomalie["gravite"] == "limite du modele"


def test_un_rotor_en_contact_avec_la_coque_est_signale(sim):
    """La panne la plus frequente et la plus difficile a voir en jeu."""
    contacts = [a for a in sim.report()["anomalies"] if a["code"] == "F5.1"]
    assert contacts
    assert "coque" in contacts[0]["titre"]
