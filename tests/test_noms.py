"""Renommage des organes : « create:analog_lever (14, 13, 20) » -> « ballast avant ».

Les noms vivent a cote du fichier de structure, jamais dedans : le `.nbt`
d'origine n'est JAMAIS ecrit.
"""
from __future__ import annotations

import json

import pytest

from createsim.data.names import Names, key_for


# --- la table de noms, sans interface --------------------------------------
def test_une_clef_est_stable_quelle_que_soit_la_forme_de_la_position():
    assert key_for("levier", (14, 13, 20)) == "levier:14,13,20"
    assert key_for("levier", [14, 13, 20]) == "levier:14,13,20"
    assert key_for("poche", 0) == "poche:0"


def test_un_nom_absent_retombe_sur_le_libelle_par_defaut():
    names = Names()
    assert names.label("levier", (1, 2, 3), "throttle lever") == "throttle lever"
    names.set("levier", (1, 2, 3), "ballast avant")
    assert names.label("levier", (1, 2, 3), "throttle lever") == "ballast avant"


def test_le_libelle_technique_n_est_jamais_perdu():
    """Un rapport doit rester rapprochable du fichier : sans les coordonnees,
    « ballast avant » ne se retrouve pas en jeu."""
    names = Names()
    assert names.describe("levier", (1, 2, 3), "levier [1, 2, 3]") == "levier [1, 2, 3]"
    names.set("levier", (1, 2, 3), "ballast avant")
    assert names.describe("levier", (1, 2, 3),
                          "levier [1, 2, 3]") == "ballast avant (levier [1, 2, 3])"


def test_un_nom_vide_efface_l_entree():
    names = Names()
    names.set("levier", (1, 2, 3), "essai")
    assert len(names) == 1
    names.set("levier", (1, 2, 3), "   ")
    assert len(names) == 0
    assert not names


def test_persistance_a_cote_du_vaisseau(tmp_path):
    nbt = tmp_path / "vaisseau.nbt"
    nbt.write_bytes(b"")
    names = Names.for_structure(str(nbt))
    assert names.path == tmp_path / "vaisseau.noms.json"

    names.set("levier", (4, 5, 6), "gaz principal")
    assert names.path.is_file()
    stored = json.loads(names.path.read_text(encoding="utf-8"))
    assert stored == {"levier:4,5,6": "gaz principal"}

    relu = Names.for_structure(str(nbt))
    assert relu.get("levier", (4, 5, 6)) == "gaz principal"


def test_effacer_le_dernier_nom_supprime_le_fichier(tmp_path):
    nbt = tmp_path / "vaisseau.nbt"
    nbt.write_bytes(b"")
    names = Names.for_structure(str(nbt))
    names.set("poche", 0, "enveloppe")
    assert names.path.is_file()
    names.set("poche", 0, "")
    assert not names.path.is_file()


def test_un_fichier_de_noms_illisible_ne_casse_rien(tmp_path):
    nbt = tmp_path / "vaisseau.nbt"
    nbt.write_bytes(b"")
    (tmp_path / "vaisseau.noms.json").write_text("{ ceci n'est pas du json",
                                                 encoding="utf-8")
    names = Names.for_structure(str(nbt))
    assert len(names) == 0
    assert names.label("levier", (0, 0, 0), "defaut") == "defaut"


def test_le_fichier_nbt_n_est_jamais_ecrit(cargo, tmp_path, monkeypatch):
    from pathlib import Path
    source = Path(cargo.structure.path)
    empreinte = (source.stat().st_size, source.stat().st_mtime_ns)
    cargo.names.path = tmp_path / "ailleurs.noms.json"
    cargo.names.set("levier", (15, 13, 20), "gaz principal")
    assert (source.stat().st_size, source.stat().st_mtime_ns) == empreinte
    assert (tmp_path / "ailleurs.noms.json").is_file()


# --- le nom remonte dans le rapport ----------------------------------------
def test_le_rapport_porte_les_noms_donnes(cargo, tmp_path):
    from createsim.sim.tick import Simulation
    cargo.names.path = tmp_path / "noms.json"
    cargo.names.set("levier", (15, 13, 20), "gaz principal")
    report = Simulation(cargo).report()
    nommees = [c for c in report["commandes"] if c.get("nom")]
    assert len(nommees) == 1
    assert nommees[0]["nom"] == "gaz principal"
    assert nommees[0]["pos"] == [15, 13, 20]
    assert report["noms"] == {"levier:15,13,20": "gaz principal"}


def test_une_anomalie_nomme_l_organe_concerne(cargo, tmp_path):
    from createsim.sim.tick import Simulation
    cargo.names.path = tmp_path / "noms.json"
    cargo.names.set("poche", 0, "enveloppe")
    anomalies = Simulation(cargo).report()["anomalies"]
    poches = [a for a in anomalies if a.get("organe", "").startswith("enveloppe")]
    assert poches, [a.get("organe") for a in anomalies]
    assert "poche 1" in poches[0]["organe"], "le libelle technique doit rester"


# --- le champ editable ------------------------------------------------------
pytest.importorskip("PySide6", reason="interface non installee")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from createsim.view.panel import ControlPanel, EditableName, LeverRow  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        try:
            app = QtWidgets.QApplication([])
        except Exception as exc:                     # pragma: no cover
            pytest.skip("pas d'affichage disponible : %s" % exc)
    return app


def _click(widget):
    event = QtGui_mouse_press(widget)
    widget.mousePressEvent(event)


def QtGui_mouse_press(widget):
    from PySide6 import QtGui
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(4, 4), QtCore.QPointF(4, 4),
        QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier)


def test_le_champ_se_lit_comme_une_etiquette_puis_s_edite_au_clic(qt_app):
    plate = EditableName("", "throttle lever · 14, 13, 20")
    assert plate.isReadOnly()
    assert plate.text() == "throttle lever · 14, 13, 20"

    _click(plate)
    assert not plate.isReadOnly(), "un clic gauche ouvre la saisie"

    plate.setText("ballast avant")
    plate._commit()
    assert plate.isReadOnly()
    assert plate.text() == "ballast avant"


def test_un_nom_vide_restaure_le_libelle_par_defaut(qt_app):
    plate = EditableName("ballast", "throttle lever")
    recu = []
    plate.renamed.connect(recu.append)
    _click(plate)
    plate.setText("   ")
    plate._commit()
    assert plate.text() == "throttle lever"
    assert recu == [""]


def test_echap_annule_la_saisie(qt_app):
    from PySide6 import QtGui
    plate = EditableName("ballast avant", "throttle lever")
    _click(plate)
    plate.setText("autre chose")
    plate.keyPressEvent(QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier))
    assert plate.text() == "ballast avant"


def test_renommer_un_levier_depuis_le_bandeau(qt_app, cargo, tmp_path):
    from createsim.sim.tick import Simulation
    cargo.names.path = tmp_path / "noms.json"
    panel = ControlPanel(cargo, Simulation(cargo))
    row = panel.findChildren(LeverRow)[0]

    _click(row.head)
    row.head.setText("ballast avant")
    row.head._commit()

    assert cargo.names.get("levier", row.lever.pos) == "ballast avant"
    assert (tmp_path / "noms.json").is_file()


def test_tous_les_organes_sont_nommables(qt_app, cargo):
    """Leviers, canaux de bruleurs, poches, transmissions, paliers."""
    from createsim.sim.tick import Simulation
    panel = ControlPanel(cargo, Simulation(cargo))
    genres = {kind for kind, _id, _plate in panel._nameplates}
    assert "canal" in genres
    assert "poche" in genres
    assert "palier" in genres
    assert len(panel.findChildren(EditableName)) >= 9
