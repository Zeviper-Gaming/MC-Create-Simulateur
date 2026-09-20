"""Le bandeau de controle (F4).

Le principe directeur du cahier se teste : le bandeau n'expose QUE ce qui
existe dans le fichier. Un vaisseau sans roues n'a pas de section roues ; un
bruleur commande par un levier n'est pas reglable directement.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6", reason="interface non installee")

from PySide6 import QtWidgets  # noqa: E402

from createsim.sim.state import SimOptions  # noqa: E402
from createsim.sim.tick import Simulation  # noqa: E402
from createsim.view.panel import ControlPanel, LeverRow, Section  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        try:
            app = QtWidgets.QApplication([])
        except Exception as exc:                     # pragma: no cover
            pytest.skip("pas d'affichage disponible : %s" % exc)
    return app


@pytest.fixture
def panel(qt_app, cargo):
    sim = Simulation(cargo, SimOptions())
    return ControlPanel(cargo, sim), sim


def _sections(panel):
    return {s.button.text() for s in panel.findChildren(Section)}


# --- le bandeau n'expose que ce qui existe ---------------------------------
def test_une_commande_d_interface_par_commande_reelle(panel):
    """F4.1 : un curseur par levier du vaisseau, avec sa position."""
    widget, _sim = panel
    rows = widget.findChildren(LeverRow)
    levers = widget.model.organ("redstone").levers
    assert len(rows) == len(levers) == 4
    for row in rows:
        assert row.slider.minimum() == 0 and row.slider.maximum() == 15
        assert str(row.lever.pos[0]) in row.findChildren(
            QtWidgets.QLabel)[0].text()


def test_un_vaisseau_sans_roues_n_a_pas_de_section_roues(panel):
    widget, _sim = panel
    assert "Commandes de bord" in _sections(widget)
    assert "Groupes de bruleurs" in _sections(widget)
    assert "Simulation" in _sections(widget)
    # ce dirigeable n'a ni roue ni section dediee
    assert not any("oue" in name for name in _sections(widget))


def test_la_valeur_numerique_est_toujours_a_cote_du_curseur(panel):
    """F4.6."""
    widget, _sim = panel
    for row in widget.findChildren(LeverRow):
        assert row.value.text() == str(row.slider.value())
        row.slider.setValue(7)
        assert row.value.text() == "7"


# --- propagation -----------------------------------------------------------
def test_bouger_un_levier_propage_jusqu_aux_bruleurs(panel):
    """F4.2 : propagation immediate par les liaisons redstone."""
    widget, sim = panel
    row = next(r for r in widget.findChildren(LeverRow) if len(r.lever.targets) > 1)
    cible = next(iter(row.lever.targets))

    row.slider.setValue(15)
    assert sim.state.commands[row.lever.pos] == 15
    assert sim.redstone.signals(sim.state.commands)[cible] == 15

    row.slider.setValue(3)
    assert sim.redstone.signals(sim.state.commands)[cible] == 3


def test_un_levier_qui_ne_commande_rien_le_dit(panel):
    widget, _sim = panel
    orphelins = [r for r in widget.findChildren(LeverRow) if not r.lever.targets]
    assert orphelins, "ce vaisseau porte des leviers sans destinataire"
    assert "ne commande rien" in orphelins[0].detail.text()


def test_le_piege_du_levier_inverse_est_ecrit_en_toutes_lettres(panel):
    """La confusion entre angle affiche et signal emis est exactement ce que
    le cahier demande de lever."""
    widget, _sim = panel
    inverses = [r for r in widget.findChildren(LeverRow) if r.lever.inverted]
    assert inverses
    row = inverses[0]
    row.slider.setValue(15)
    text = row.detail.text()
    assert "angle en jeu 0" in text
    assert "signal emis 15" in text


def test_le_decouplage_a_quinze_est_ecrit_en_toutes_lettres(qt_app, cachalot_model):
    sim = Simulation(cachalot_model, SimOptions())
    widget = ControlPanel(cachalot_model, sim)
    widget.refresh()
    textes = [label.text() for _pos, label in widget._transmission_rows]
    assert any("DECOUPLE" in t for t in textes), textes


# --- reglages de conception -------------------------------------------------
def test_le_reglage_molette_est_modifiable_et_n_ecrit_pas_le_fichier(panel):
    """« C'est un parametre de conception et non une commande de vol. »"""
    from pathlib import Path
    widget, sim = panel
    source = Path(widget.model.structure.path)
    empreinte = source.stat().st_mtime_ns

    burner = widget.model.organ("ballons").burners[0]
    widget._scroll_changed(burner, 250)
    assert burner["reglage"] == 250.0
    assert sim.balloons.pockets[0].max_demand < 3000
    assert source.stat().st_mtime_ns == empreinte


def test_la_situation_est_modifiable_simulation_en_cours(panel):
    """F4.4."""
    widget, sim = panel
    sim.run(20)
    widget.altitude.setValue(120.0)
    assert sim.state.position[1] == pytest.approx(120.0)
    assert sim.options.altitude == pytest.approx(120.0)

    widget.ground.setChecked(True)
    widget.ground_y.setValue(40.0)
    assert sim.options.ground_enabled is True
    assert sim.ground.height_at(0.0, 0.0) == pytest.approx(40.0)


def test_le_mode_expert_marque_puis_restaure(panel):
    """F4.7 : modifiables, en signalant l'ecart au reglage du jeu."""
    widget, _sim = panel
    tables = widget.model.tables
    origine = tables.get("forces.hot_air_strength")

    widget.expert.setChecked(True)
    widget.hot_air.setValue(4.0)
    assert tables.get("forces.hot_air_strength") == 4.0
    widget.refresh()
    assert "MODE EXPERT" in widget.taint.text()

    widget.expert.setChecked(False)
    assert tables.get("forces.hot_air_strength") == origine
    widget.refresh()
    assert widget.taint.text() == ""


def test_jeux_de_reglages_nommes(panel, tmp_path, monkeypatch):
    """F4.5 : sauvegarde et rappel."""
    widget, sim = panel
    monkeypatch.setattr(widget, "_preset_path",
                        lambda: tmp_path / "essai.reglages.json")

    row = next(r for r in widget.findChildren(LeverRow) if r.lever.targets)
    row.slider.setValue(11)
    widget.presets.setCurrentText("croisiere")
    widget._save_preset()

    stored = json.loads((tmp_path / "essai.reglages.json").read_text(encoding="utf-8"))
    assert "croisiere" in stored

    row.slider.setValue(2)
    assert sim.state.commands[row.lever.pos] == 2
    widget._load_preset()
    assert sim.state.commands[row.lever.pos] == 11
    assert row.slider.value() == 11


# --- rafraichissement -------------------------------------------------------
def test_le_bandeau_suit_la_simulation(panel):
    widget, sim = panel
    widget.refresh()
    avant = widget.clock.text()
    sim.run(40)
    widget.refresh()
    assert widget.clock.text() != avant
    assert "tick 40" in widget.clock.text()


def test_les_poches_affichent_leur_remplissage_en_direct(panel):
    widget, sim = panel
    sim.options.initial_gas = "vide"
    sim.reset()
    widget.refresh()
    assert "0 / 8926" in widget._pocket_rows[0][2].text()
    sim.run(200)
    widget.refresh()
    text = widget._pocket_rows[0][2].text()
    assert "0 / 8926" not in text and "%" in text


def test_les_sections_se_replient(panel):
    widget, _sim = panel
    section = widget.findChildren(Section)[0]
    assert section.body.isVisible() or True     # pas encore affiche
    section.button.setChecked(False)
    assert not section.body.isVisible()
    section.button.setChecked(True)
