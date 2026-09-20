"""Courbe temporelle de deux ou trois grandeurs, sur une fenetre glissante.

C'est la qu'on voit un vaisseau osciller autour de son altitude d'equilibre au
lieu de s'y poser — un tableau de nombres ne le montre jamais, parce que
l'oscillation est dans la DERIVEE et pas dans la valeur.

Chaque serie porte sa propre echelle : l'altitude se compte en centaines et la
vitesse en unites, les forcer sur un axe commun ecraserait l'une des deux. Une
trace de reference chargee depuis un CSV se superpose en pointille, ce qui
permet de mesurer une amelioration au lieu de la deviner.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

PANEL = QtGui.QColor(14, 16, 20)
GRID = QtGui.QColor(255, 255, 255, 20)
TEXT = QtGui.QColor(226, 230, 236)
DIM = QtGui.QColor(150, 158, 170)

#: grandeurs offertes au choix, avec leur colonne de trace et leur couleur
SERIES = {
    "altitude": ("y", (0.42, 0.78, 1.00), "m"),
    "vitesse verticale": ("vitesse_verticale", (0.34, 0.92, 0.58), "blocs/s"),
    "vitesse horizontale": ("vitesse_horizontale", (1.00, 0.72, 0.26), "blocs/s"),
    "vitesse": ("vitesse", (0.96, 0.52, 0.86), "blocs/s"),
    "gaz total": ("gaz_total", (0.72, 0.56, 1.00), "m³"),
    "portance": ("portance", (0.38, 0.74, 1.00), ""),
    "poids": ("poids", (0.95, 0.35, 0.35), ""),
    "poussee": ("poussee", (0.34, 0.92, 0.58), ""),
    "trainee": ("trainee", (0.96, 0.52, 0.86), ""),
    "resultante verticale": ("resultante_y", (1.00, 1.00, 1.00), ""),
    "pression": ("pression", (0.60, 0.80, 0.95), ""),
    "regime max": ("regime_max", (0.83, 0.62, 0.24), "tr/min"),
    "Stress Units": ("stress_su", (1.00, 0.86, 0.32), "SU"),
}
DEFAULTS = ("altitude", "vitesse verticale", "gaz total")


class CurveView(QtWidgets.QWidget):
    """Le trace lui-meme. Peint a la main : aucune dependance de plus."""

    PAD_LEFT = 8
    PAD_RIGHT = 74
    PAD_TOP = 6
    PAD_BOTTOM = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(130)
        self.trace = None
        self.reference = None
        self.selected = list(DEFAULTS)
        self.window_seconds = 30.0

    def set_trace(self, trace) -> None:
        self.trace = trace
        self.update()

    def set_reference(self, trace) -> None:
        self.reference = trace
        self.update()

    def set_series(self, index: int, name: str) -> None:
        while len(self.selected) <= index:
            self.selected.append("")
        self.selected[index] = name
        self.update()

    # -- rendu -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), PANEL)
        plot = QtCore.QRectF(
            self.PAD_LEFT, self.PAD_TOP,
            max(10.0, self.width() - self.PAD_LEFT - self.PAD_RIGHT),
            max(10.0, self.height() - self.PAD_TOP - self.PAD_BOTTOM))

        rows = self.trace.window(self.window_seconds) if self.trace else []
        self._grid(painter, plot, rows)
        if len(rows) < 2:
            painter.setPen(DIM)
            painter.drawText(plot, QtCore.Qt.AlignmentFlag.AlignCenter,
                             "lancer la simulation pour tracer")
            painter.end()
            return

        start, end = rows[0]["temps_s"], rows[-1]["temps_s"]
        span = max(end - start, 1e-6)
        slot = 0
        for name in self.selected:
            entry = SERIES.get(name)
            if entry is None:
                continue
            column, color, unit = entry
            self._series(painter, plot, rows, column, color, unit, name,
                         start, span, slot)
            slot += 1
        painter.end()

    def _grid(self, painter, plot, rows) -> None:
        painter.setPen(QtGui.QPen(GRID, 1))
        for i in range(5):
            y = plot.top() + plot.height() * i / 4.0
            painter.drawLine(QtCore.QPointF(plot.left(), y),
                             QtCore.QPointF(plot.right(), y))
        painter.setPen(DIM)
        font = painter.font()
        font.setPointSize(8)
        font.setFamily("Consolas")
        painter.setFont(font)
        if rows:
            painter.drawText(
                QtCore.QPointF(plot.left(), plot.bottom() + 12),
                "%.1f s" % rows[0]["temps_s"])
            painter.drawText(
                QtCore.QPointF(plot.right() - 46, plot.bottom() + 12),
                "%.1f s" % rows[-1]["temps_s"])

    def _series(self, painter, plot, rows, column, color, unit, name,
                start, span, slot) -> None:
        values = [r.get(column) for r in rows]
        values = [v for v in values if isinstance(v, (int, float))]
        if not values:
            return
        low, high = min(values), max(values)
        if high - low < 1e-9:
            low, high = low - 0.5, high + 0.5
        scale = plot.height() / (high - low)

        pen = QtGui.QPen(QtGui.QColor.fromRgbF(*color), 1.6)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        started = False
        for row in rows:
            value = row.get(column)
            if not isinstance(value, (int, float)):
                continue
            x = plot.left() + plot.width() * (row["temps_s"] - start) / span
            y = plot.bottom() - (value - low) * scale
            if started:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                started = True
        painter.drawPath(path)

        # la trace de reference, en pointille et sur LA MEME echelle
        if self.reference is not None and len(self.reference) > 1:
            ghost = QtGui.QColor.fromRgbF(*color)
            ghost.setAlpha(110)
            painter.setPen(QtGui.QPen(ghost, 1.2, QtCore.Qt.PenStyle.DashLine))
            path = QtGui.QPainterPath()
            started = False
            for row in self.reference.rows:
                value = row.get(column)
                time = row.get("temps_s")
                if not isinstance(value, (int, float)) or time is None:
                    continue
                if time < start or time > start + span:
                    continue
                x = plot.left() + plot.width() * (time - start) / span
                y = plot.bottom() - (value - low) * scale
                if started:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                    started = True
            painter.drawPath(path)

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QtGui.QColor.fromRgbF(*color))
        current = values[-1]
        text = "%s %s" % (_short(current), unit)
        painter.drawText(QtCore.QPointF(plot.right() + 6,
                                        plot.top() + 11 + slot * 26), text.strip())
        painter.setPen(DIM)
        painter.drawText(QtCore.QPointF(plot.right() + 6,
                                        plot.top() + 22 + slot * 26),
                         "%s…%s" % (_short(low), _short(high)))


def _short(value: float) -> str:
    if abs(value) >= 10000:
        return "%.0f" % value
    if abs(value) >= 100:
        return "%.0f" % value
    if abs(value) >= 1:
        return "%.2f" % value
    return "%.3f" % value


class CurvePanel(QtWidgets.QWidget):
    """Le trace, plus le choix des grandeurs et de la fenetre."""

    reference_requested = QtCore.Signal()
    export_requested = QtCore.Signal()
    replay_requested = QtCore.Signal()
    replay_seek = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 4)
        layout.setSpacing(4)

        self.view = CurveView()
        bar = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        self.combos = []
        for index, default in enumerate(DEFAULTS):
            combo = QtWidgets.QComboBox()
            combo.addItem("—")
            combo.addItems(list(SERIES))
            combo.setCurrentText(default)
            combo.currentTextChanged.connect(
                lambda text, i=index: self.view.set_series(i, text))
            row.addWidget(combo)
            self.combos.append(combo)

        row.addStretch(1)
        row.addWidget(QtWidgets.QLabel("fenetre"))
        self.window = QtWidgets.QSpinBox()
        self.window.setRange(5, 600)
        self.window.setValue(30)
        self.window.setSuffix(" s")
        self.window.valueChanged.connect(self._window_changed)
        row.addWidget(self.window)

        reference = QtWidgets.QToolButton()
        reference.setText("reference…")
        reference.setToolTip("charger une trace CSV et la superposer")
        reference.clicked.connect(self.reference_requested.emit)
        row.addWidget(reference)

        export = QtWidgets.QToolButton()
        export.setText("export CSV")
        export.clicked.connect(self.export_requested.emit)
        row.addWidget(export)

        replay = QtWidgets.QToolButton()
        replay.setText("rejouer…")
        replay.setToolTip("relire une trace enregistree, tick par tick")
        replay.clicked.connect(self.replay_requested.emit)
        row.addWidget(replay)

        # barre de rejeu, cachee tant qu'aucune trace n'est relue
        self.replay_bar = QtWidgets.QWidget()
        replay_row = QtWidgets.QHBoxLayout(self.replay_bar)
        replay_row.setContentsMargins(0, 0, 0, 0)
        self.replay_label = QtWidgets.QLabel()
        self.replay_label.setStyleSheet("color: #ffd27a;")
        replay_row.addWidget(self.replay_label)
        self.replay_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.replay_slider.valueChanged.connect(self.replay_seek.emit)
        replay_row.addWidget(self.replay_slider, 1)
        self.replay_bar.setVisible(False)

        layout.addWidget(self.view, 1)
        layout.addWidget(bar)
        layout.addWidget(self.replay_bar)

    def _window_changed(self, value: int) -> None:
        self.view.window_seconds = float(value)
        self.view.update()

    def set_trace(self, trace) -> None:
        self.view.set_trace(trace)

    def set_reference(self, trace) -> None:
        self.view.set_reference(trace)

    def start_replay(self, trace) -> None:
        self.replay_slider.blockSignals(True)
        self.replay_slider.setRange(0, max(0, len(trace) - 1))
        self.replay_slider.setValue(0)
        self.replay_slider.blockSignals(False)
        self.replay_bar.setVisible(True)
        self.set_replay_position(0, trace)

    def set_replay_position(self, index: int, trace) -> None:
        row = trace.rows[index] if 0 <= index < len(trace) else {}
        self.replay_label.setText(
            "REJEU · tick %d · %.2f s" % (row.get("tick", 0),
                                          row.get("temps_s", 0.0)))

    def stop_replay(self) -> None:
        self.replay_bar.setVisible(False)

    def refresh(self) -> None:
        self.view.update()
