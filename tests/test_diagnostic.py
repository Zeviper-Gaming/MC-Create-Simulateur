"""Le panneau de diagnostic (F5) : lister, classer, et surtout SITUER.

« Rotor soude a la coque » ne sert a rien si on doit ensuite chercher ou.
Et une limite du modele n'est pas un defaut du vaisseau : les confondre coute
a l'utilisateur une recherche de panne inexistante.
"""
from __future__ import annotations

import pytest

from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation

pytest.importorskip("PySide6", reason="interface non installee")

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from createsim.view.diagnostics import (SEVERITY, AnomalyRow,  # noqa: E402
                                        DiagnosticsPanel)


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
def anomalies(cargo):
    return Simulation(cargo, SimOptions()).report()["anomalies"]


# --- ce que le noyau produit ------------------------------------------------
def test_le_vaisseau_de_reference_a_des_anomalies(anomalies):
    codes = {a["code"] for a in anomalies}
    assert "F5.1" in codes, "ce cargo a deux rotors en contact avec la coque"
    assert all(a.get("gravite") in SEVERITY for a in anomalies)


def test_chaque_anomalie_situe_ses_blocs(anomalies):
    for anomaly in anomalies:
        if anomaly["code"] in ("F5.8",):
            continue        # une incertitude de masse n'a pas de bloc precis
        assert anomaly.get("blocs"), anomaly["code"]
        for block in anomaly["blocs"]:
            assert len(block) == 3


def test_une_limite_du_modele_n_est_pas_un_defaut(cargo):
    """F5.7 et F5.8 : signalees comme limites, jamais comme defauts."""
    from createsim.model.vehicle import VehicleModel
    from pathlib import Path
    cruiser = Path(r"C:/Users/Florian/curseforge/minecraft/Instances"
                   r"/La Bonne Compagnie/schematics/c1_air_cruiser.nbt")
    if not cruiser.is_file():
        pytest.skip("vaisseau hors depot")
    report = Simulation(VehicleModel.load(str(cruiser))).report()
    limites = [a for a in report["anomalies"]
               if a["code"] in ("F5.7", "F5.8", "F6.9")]
    assert limites
    for anomaly in limites:
        assert anomaly["gravite"] == "limite du modele"


# --- le panneau -------------------------------------------------------------
def test_le_panneau_liste_les_anomalies(qt_app, anomalies):
    panel = DiagnosticsPanel()
    panel.set_anomalies(anomalies)
    assert len(panel._rows) == len(anomalies)
    assert "anomalie" in panel.summary.text()


def test_les_graves_passent_en_premier(qt_app):
    panel = DiagnosticsPanel()
    panel.set_anomalies([
        {"code": "F5.8", "gravite": "limite du modele", "titre": "hors table",
         "detail": "", "blocs": []},
        {"code": "F5.1", "gravite": "grave", "titre": "rotor", "detail": "",
         "blocs": [[1, 2, 3]]},
        {"code": "F5.3", "gravite": "faible", "titre": "poche", "detail": "",
         "blocs": [[4, 5, 6]]},
    ])
    codes = [row.anomaly["code"] for row in panel._rows]
    assert codes == ["F5.1", "F5.3", "F5.8"]


def test_cliquer_une_anomalie_emet_ses_blocs(qt_app, anomalies):
    panel = DiagnosticsPanel()
    panel.set_anomalies(anomalies)
    recu = []
    panel.anomaly_selected.connect(recu.append)

    row = next(r for r in panel._rows if r.anomaly.get("blocs"))
    row.mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(3, 3), QtCore.QPointF(3, 3),
        QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier))
    assert recu and recu[0]["blocs"]


def test_une_anomalie_sans_bloc_n_est_pas_cliquable(qt_app):
    panel = DiagnosticsPanel()
    panel.set_anomalies([{"code": "F5.8", "gravite": "limite du modele",
                          "titre": "hors table", "detail": "", "blocs": []}])
    recu = []
    panel.anomaly_selected.connect(recu.append)
    panel._rows[0].mousePressEvent(QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(3, 3), QtCore.QPointF(3, 3),
        QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier))
    assert recu == []


def test_la_liste_ne_se_reconstruit_pas_pour_rien(qt_app, anomalies):
    """Elle est recalculee a chaque tick mais ne bouge presque jamais :
    rebatir des widgets vingt fois par seconde ferait tomber la boucle."""
    panel = DiagnosticsPanel()
    panel.set_anomalies(anomalies)
    avant = list(panel._rows)
    panel.set_anomalies(list(anomalies))
    assert panel._rows == avant, "aucun widget recree a contenu identique"

    panel.set_anomalies(anomalies[:-1])
    assert panel._rows != avant


def test_un_vaisseau_sain_le_dit(qt_app):
    panel = DiagnosticsPanel()
    panel.set_anomalies([])
    assert panel._rows == []
    assert "aucune" in panel.summary.text()
