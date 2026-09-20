"""Panneau de diagnostic : les defauts invisibles en jeu (F5).

Chaque anomalie est cliquable, et met en evidence les blocs concernes dans la
vue 3D. C'est tout l'interet : « rotor soude a la coque » ne sert a rien si on
doit ensuite chercher OU.

Une distinction est tenue partout, parce que la confondre coute une recherche
de panne inexistante : une LIMITE DU MODELE n'est pas un defaut du vaisseau.
Un reseau sans source identifiee veut dire que le solveur n'a pas su le relier,
pas que la construction est fautive.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

SEVERITY = {
    "grave": ("#ff6b6b", 0),
    "moyen": ("#ffb060", 1),
    "faible": ("#8fa6c0", 2),
    "limite du modele": ("#b79cff", 3),
}
DEFAULT = ("#9aa2ae", 4)


class AnomalyRow(QtWidgets.QFrame):
    """Une anomalie, cliquable pour la situer dans le vaisseau."""

    selected = QtCore.Signal(object)

    def __init__(self, anomaly: dict, parent=None):
        super().__init__(parent)
        self.anomaly = anomaly
        color, _rank = SEVERITY.get(anomaly.get("gravite", ""), DEFAULT)
        blocks = anomaly.get("blocs") or []
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor if blocks
                       else QtCore.Qt.CursorShape.ArrowCursor)
        self.setStyleSheet(
            "QFrame { border: 1px solid #2a2f38; border-left: 3px solid %s;"
            " border-radius: 3px; }" % color)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(7, 4, 6, 4)
        layout.setSpacing(1)

        head = QtWidgets.QLabel("%s · %s" % (anomaly.get("code", "?"),
                                             anomaly.get("titre", "")))
        head.setStyleSheet("color: %s; font-weight: bold; border: none;" % color)
        head.setWordWrap(True)
        layout.addWidget(head)

        organe = anomaly.get("organe")
        if organe:
            tag = QtWidgets.QLabel(organe)
            tag.setStyleSheet("color: #e2e6ec; border: none;")
            tag.setWordWrap(True)
            layout.addWidget(tag)

        detail = QtWidgets.QLabel(anomaly.get("detail", ""))
        detail.setStyleSheet("color: #9aa2ae; border: none;")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        if blocks:
            hint = QtWidgets.QLabel("%d bloc(s) concerne(s) — clic pour situer"
                                    % len(blocks))
            hint.setStyleSheet("color: #6f7886; border: none; font-style: italic;")
            layout.addWidget(hint)

    def mousePressEvent(self, event) -> None:
        if self.anomaly.get("blocs"):
            self.selected.emit(self.anomaly)
        super().mousePressEvent(event)


class DiagnosticsPanel(QtWidgets.QScrollArea):
    """La liste deroulante des anomalies detectees."""

    anomaly_selected = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QtWidgets.QWidget()
        self.column = QtWidgets.QVBoxLayout(container)
        self.column.setContentsMargins(6, 6, 6, 6)
        self.column.setSpacing(5)
        self.setWidget(container)

        self.summary = QtWidgets.QLabel()
        self.summary.setStyleSheet("color: #78c8ff; font-weight: bold;")
        self.summary.setWordWrap(True)
        self.column.addWidget(self.summary)
        self.column.addStretch(1)
        self._rows: list[AnomalyRow] = []
        self._signature = None

    def set_anomalies(self, anomalies: list[dict]) -> None:
        """Ne reconstruit la liste que si elle a change.

        Elle est recalculee a chaque tick, mais ne bouge presque jamais :
        rebatir des dizaines de widgets vingt fois par seconde ferait tomber
        la boucle sous son seuil.
        """
        signature = tuple((a.get("code"), a.get("detail")) for a in anomalies)
        if signature == self._signature:
            return
        self._signature = signature

        for row in self._rows:
            self.column.removeWidget(row)
            row.deleteLater()
        self._rows = []

        ordered = sorted(anomalies,
                         key=lambda a: SEVERITY.get(a.get("gravite", ""),
                                                    DEFAULT)[1])
        counts: dict[str, int] = {}
        for anomaly in ordered:
            counts[anomaly.get("gravite", "?")] = counts.get(
                anomaly.get("gravite", "?"), 0) + 1
        if not ordered:
            self.summary.setText("aucune anomalie detectee")
        else:
            self.summary.setText(
                "%d anomalie(s) : %s" % (len(ordered),
                                         ", ".join("%d %s" % (n, k)
                                                   for k, n in counts.items())))
        for index, anomaly in enumerate(ordered):
            row = AnomalyRow(anomaly)
            row.selected.connect(self.anomaly_selected.emit)
            self.column.insertWidget(index + 1, row)
            self._rows.append(row)
