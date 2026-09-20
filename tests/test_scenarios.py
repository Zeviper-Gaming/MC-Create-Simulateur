"""Scenarios, comparaison, non-regression (L4).

Le lot repond a deux questions que les lots precedents ne posaient pas :

    « est-ce que ma modification a servi a quelque chose ? »
    « qu'est-ce que la mise a jour du mod a change chez moi ? »

Les deux reposent sur une seule propriete : un scenario doit se rejouer A
L'IDENTIQUE. Si deux executions du meme scenario different, toute comparaison
mesure du bruit.

Le test qui compte vraiment est celui qui verifie que la non-regression
DETECTE un changement. Une non-regression qui passe toujours ne protege de
rien, et c'est le mode de defaillance naturel de ce genre d'outil.
"""
from __future__ import annotations

import pytest

from createsim.data.tables import Tables
from createsim.sim.compare import Delta, compare, first_divergence, indicators
from createsim.sim.scenario import (Recorder, Scenario, Step, library, locate,
                                    parse_pos)
from createsim.sim.state import SimOptions
from createsim.sim.telemetry import Trace
from createsim.sim.tick import Simulation
from createsim.validation import level4_nonregression

BRULEUR = (15, 13, 20)


@pytest.fixture
def montee() -> Scenario:
    return Scenario(
        nom="montee d'essai", vaisseau="cargo_airship.nbt", ticks=300,
        echantillon=5, options=SimOptions(altitude=63.0, initial_gas="vide"),
        commandes=(Step(0, BRULEUR, 9),))


# --- le scenario ------------------------------------------------------------
def test_un_scenario_se_rejoue_a_l_identique(montee):
    """La propriete dont tout le reste depend."""
    a, b = montee.run(), montee.run()
    assert len(a) == len(b)
    for row_a, row_b in zip(a.rows, b.rows):
        assert row_a == row_b


def test_un_scenario_fait_l_aller_retour_par_le_fichier(montee, tmp_path):
    path = montee.save(tmp_path / "essai.json")
    relu = Scenario.load(path)
    assert relu.nom == montee.nom
    assert relu.ticks == montee.ticks
    assert relu.commandes == montee.commandes
    assert relu.options == montee.options
    for row_a, row_b in zip(montee.run().rows, relu.run().rows):
        assert row_a == row_b


def test_le_format_est_lisible_a_la_main(montee, tmp_path):
    """Exigence du cahier : « scenarios et traces dans des formats ouverts et
    lisibles a la main »."""
    text = montee.save(tmp_path / "essai.json").read_text(encoding="utf-8")
    assert '"nom"' in text and '"commandes"' in text
    assert '"levier": "15,13,20"' in text, text
    assert "\n" in text, "un JSON sur une ligne n'est pas lisible a la main"


def test_les_commandes_sont_horodatees(montee):
    """« Brûleurs a fond » et « brûleurs a fond puis coupes a la seconde 30 »
    ne decrivent pas la meme manoeuvre."""
    coupe = Scenario(nom="coupe", vaisseau=montee.vaisseau, ticks=montee.ticks,
                     echantillon=5, options=montee.options,
                     commandes=(Step(0, BRULEUR, 15), Step(100, BRULEUR, 0)))
    gaz_continu = montee.run().column("gaz_total")
    gaz_coupe = coupe.run().column("gaz_total")
    assert gaz_coupe[-1] < gaz_continu[-1], "couper le gaz doit se voir"
    assert gaz_coupe[5] > 0, "avant la coupure, le ballon se remplit"


def test_un_reglage_passe_forcement_par_le_mode_expert(montee):
    """Un scenario regle ne doit pas pouvoir se faire passer pour une mesure
    de reference : le mode expert marque toute grandeur calculee."""
    regle = Scenario(nom="regle", vaisseau=montee.vaisseau, ticks=50,
                     options=montee.options,
                     reglages={"forces.hot_air_strength": 9.0})
    tables = regle.tables(Tables.load())
    assert tables.expert_mode is True
    assert tables.tainted is True
    assert "forces.hot_air_strength" in tables.tainted_keys


def test_un_vaisseau_absent_le_dit_au_lieu_de_planter():
    absent = Scenario(nom="fantome", vaisseau="vaisseau_qui_n_existe_pas.nbt")
    assert locate(absent.vaisseau) is None
    with pytest.raises(FileNotFoundError):
        absent.run()


def test_un_scenario_impose_sa_situation_a_la_session(cargo):
    """Charger un scenario avec un sol sur une session sans sol donnait une
    chute sans fin : le sol etait fige a la construction de la Simulation."""
    sim = Simulation(cargo, SimOptions(altitude=63.0))
    assert sim.ground.height_at(0.0, 0.0) == float("-inf")

    pose = Scenario(nom="pose", vaisseau="cargo_airship.nbt", ticks=400,
                    echantillon=1,
                    options=SimOptions(altitude=63.0, initial_gas="vide",
                                       ground_enabled=True,
                                       ground_altitude=10.0))
    sim.options = pose.options
    trace = pose.run(sim=sim)
    assert min(trace.column("y")) > 10.0, "le sol du scenario doit s'appliquer"
    assert sum(trace.column("au_sol")) > 0, "le vaisseau a vide doit se poser"


def test_une_position_de_levier_se_relit(montee):
    assert parse_pos("15,13,20") == (15, 13, 20)
    assert parse_pos(" 15 , 13 , 20 ") == (15, 13, 20)


# --- la capture -------------------------------------------------------------
def test_une_session_se_fige_en_scenario(cargo):
    sim = Simulation(cargo, SimOptions(initial_gas="vide"))
    recorder = Recorder(sim)
    sim.run(40)
    sim.set_command(BRULEUR, 3)
    recorder.capture()
    sim.run(40)
    sim.set_command(BRULEUR, 12)
    recorder.capture()

    scenario = recorder.scenario("session", "cargo_airship.nbt")
    valeurs = [(s.tick, s.value) for s in scenario.commandes
               if s.lever == BRULEUR]
    assert valeurs[0][0] == 0
    assert (40, 3) in valeurs and (80, 12) in valeurs
    assert scenario.ticks >= 80


def test_seul_un_changement_est_enregistre(cargo):
    """Consigner chaque levier a chaque tick donnerait un fichier illisible,
    ce que le cahier interdit — et rejouable a l'identique tout de meme."""
    sim = Simulation(cargo, SimOptions())
    recorder = Recorder(sim)
    depart = len(recorder.steps)
    for _ in range(50):
        sim.step()
        recorder.capture()
    assert len(recorder.steps) == depart, "rien n'a bouge, rien n'est consigne"


def test_une_session_figee_se_rejoue(cargo):
    sim = Simulation(cargo, SimOptions(initial_gas="vide"))
    recorder = Recorder(sim)
    sim.set_command(BRULEUR, 11)
    recorder.capture()
    sim.run(100)

    scenario = recorder.scenario("rejeu", "cargo_airship.nbt")
    scenario.ticks = 100
    scenario.echantillon = 1
    trace = scenario.run()
    # la trace arrondit a 4 decimales pour rester lisible a la main : c'est la
    # seule difference entre la session et son rejeu.
    assert trace.last()["y"] == pytest.approx(sim.state.position[1], abs=1e-4)


# --- la comparaison ---------------------------------------------------------
def test_deux_traces_identiques_ne_bougent_pas(montee):
    result = compare(montee.run(), montee.run())
    assert result.identique
    assert result.verdict == "identique"
    assert result.divergence_tick is None
    assert result.bouges == []


def test_la_comparaison_date_la_divergence(montee):
    """L'information que les indicateurs ne donnent pas : l'INSTANT. Un ecart
    de 3 % sur l'altitude finale ne dit pas s'il nait au depart ou derive."""
    tard = Scenario(nom="coupe tard", vaisseau=montee.vaisseau,
                    ticks=montee.ticks, echantillon=1, options=montee.options,
                    commandes=(Step(0, BRULEUR, 9), Step(200, BRULEUR, 0)))
    tot = Scenario(nom="identique au debut", vaisseau=montee.vaisseau,
                   ticks=montee.ticks, echantillon=1, options=montee.options,
                   commandes=(Step(0, BRULEUR, 9),))
    result = compare(tot.run(), tard.run())
    assert result.divergence_tick is not None
    assert result.divergence_tick >= 200, (
        "les deux executions sont identiques jusqu'a la coupure, tick %s"
        % result.divergence_tick)


def test_un_indicateur_absent_est_signale_pas_ignore():
    """Taire une colonne manquante laisserait croire que tout va bien parce
    que la moitie du bilan n'a pas ete regardee."""
    delta = Delta("essai", 1.0, None, "m", 0.01)
    assert delta.absent
    assert delta.bouge, "un indicateur absent doit ressortir"
    assert delta.ecart is None
    assert "ABSENT" in delta.line()


def test_un_ecart_relatif_sur_une_reference_nulle_ne_ment_pas():
    delta = Delta("essai", 0.0, 5.0, "m", 0.01)
    assert delta.relatif is None, "diviser par zero n'apprend rien de plus"
    assert delta.bouge


def test_les_indicateurs_couvrent_ce_qu_on_regarde(montee):
    values = indicators(montee.run())
    for name in ("altitude finale", "vitesse verticale max", "gaz final",
                 "SU demandes max", "ticks en surcharge"):
        assert name in values, name
    assert values["altitude finale"] is not None


def test_une_rupture_se_distingue_d_une_derive(montee):
    grosse = Scenario(nom="grosse", vaisseau=montee.vaisseau, ticks=montee.ticks,
                      echantillon=5, options=montee.options,
                      commandes=(Step(0, BRULEUR, 0),))
    assert compare(montee.run(), grosse.run()).verdict == "rupture"


# --- la bibliotheque et la non-regression -----------------------------------
def test_la_bibliotheque_est_chargeable():
    scenarios = library()
    assert scenarios, "data/scenarios est vide"
    for scenario in scenarios:
        assert scenario.nom and scenario.vaisseau
        assert scenario.question, "%s : a quelle question repond-il ?" % scenario.nom
        assert scenario.ticks > 0


def test_chaque_scenario_de_reference_a_sa_trace():
    for scenario in library():
        if locate(scenario.vaisseau) is None:
            continue
        assert scenario.reference_path().is_file(), (
            "%s : lancer `createsim scenario bless`" % scenario.nom)


def test_la_non_regression_passe_sur_les_tables_du_depot():
    results = [r for r in level4_nonregression(Tables.load())
               if "IGNORE" not in r["detail"]]
    assert results, "aucun scenario rejouable"
    for r in results:
        assert r["passe"], "%s : %s" % (r["nom"], r["detail"])


def test_la_non_regression_detecte_une_mise_a_jour_de_mod():
    """LE test du lot. Une non-regression qui passe toujours ne protege de
    rien, et c'est le mode de defaillance naturel de ce genre d'outil.

    On simule ici ce que fait une version d'Aeronautics : la poussee d'air
    chaud gagne 3 %.
    """
    tables = Tables.load()
    tables.expert_mode = True
    tables.override("forces.hot_air_strength",
                    tables.get("forces.hot_air_strength") * 1.03)

    results = [r for r in level4_nonregression(tables)
               if "IGNORE" not in r["detail"] and "pas de reference" not in r["detail"]]
    echecs = [r for r in results if not r["passe"]]
    assert echecs, "un changement de constante doit se voir"

    premier = echecs[0]
    assert premier["details"], "dire CE QUI a bouge, pas seulement QUE ca a bouge"
    assert premier["mesure"]["divergence"], "et a partir de quel tick"


def test_un_scenario_sans_reference_n_est_pas_une_regression(tmp_path):
    """Le confondre avec une regression ferait crier au loup a chaque ajout."""
    scenario = Scenario(nom="tout neuf", vaisseau="cargo_airship.nbt",
                        ticks=20, question="?")
    scenario.save(tmp_path / "99-neuf.json")
    results = level4_nonregression(Tables.load(), tmp_path)
    assert len(results) == 1
    assert results[0]["passe"] is True
    assert "reference" in results[0]["detail"]


def test_une_trace_de_reference_est_relisible():
    """Format ouvert : la reference doit se relire sans l'outil qui l'a ecrite."""
    for scenario in library():
        path = scenario.reference_path()
        if not path.is_file():
            continue
        trace = Trace.from_csv(str(path))
        assert len(trace) > 1
        assert "y" in trace.rows[0]
        tick, _column, _second = first_divergence(trace, trace)
        assert tick is None, "une trace ne diverge pas d'elle-meme"
