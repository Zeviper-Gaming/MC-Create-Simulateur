"""Bandeau d'instrumentation et legende chiffree, en surimpression.

Le cahier demande un bandeau discret : altitude, vitesse, assiette, portance
totale contre poids, regime maximal, charge en Stress Units. Et une legende
chiffree a cote du code couleur des forces (F3.7) — une couleur sans son
nombre ne repond a aucune des six questions du cahier.

Peint avec QPainter par-dessus la vue OpenGL, et transparent aux clics : la
camera reste pilotable a travers.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

PANEL = QtGui.QColor(14, 16, 20, 208)
BORDER = QtGui.QColor(255, 255, 255, 28)
TEXT = QtGui.QColor(226, 230, 236)
DIM = QtGui.QColor(150, 158, 170)
ACCENT = QtGui.QColor(120, 200, 255)
WARN = QtGui.QColor(255, 176, 96)


def number(value: float, digits: int = 1, unit: str = "") -> str:
    """Nombre a la francaise : espace fine pour les milliers, virgule decimale."""
    if value is None:
        return "—"
    if abs(value) >= 10000:
        text = "{:,.0f}".format(value).replace(",", " ")
    else:
        text = ("{:,.%df}" % digits).format(value)
        text = text.replace(",", " ").replace(".", ",")
    return text + (" " + unit if unit else "")


class Hud(QtWidgets.QWidget):
    """Surimpression : instruments en haut, legende des forces en bas."""

    MARGIN = 14
    PAD = 12
    LINE = 19

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        self.title = ""
        self.instruments: list[tuple[str, str, bool]] = []
        self.legend: list[dict] = []
        self.visible_groups: set[str] = set()
        self.footer = ""
        self.scale_text = ""
        self.mode = ""

    # -- contenu -----------------------------------------------------------
    def set_report(self, title: str, report: dict, overlay) -> None:
        self.title = title
        bilan = report.get("bilan") or {}
        cinetique = report.get("cinetique") or {}
        stress = report.get("stress") or []
        situation = report.get("situation") or {}
        charge = sum(n["stress_su"] for n in stress)
        capacite = sum(n["capacite_su"] for n in stress)
        tangage = bilan.get("tangage") or {}
        surcharge = bool(report.get("surcharge"))
        ratio = bilan.get("ratio_portance_poids")

        self.instruments = [
            ("masse", number(report.get("masse"), 1), False),
            ("poids", number(bilan.get("poids"), 0), False),
            ("portance", number(bilan.get("portance_actuelle"), 0), False),
            ("portance / poids", number(ratio, 3) if ratio else "—",
             bool(ratio and ratio < 1.0)),
            ("altitude", number(situation.get("altitude"), 1, "m"), False),
            ("altitude d'equilibre",
             number(bilan.get("altitude_equilibre"), 1, "m"), False),
            ("regime max", number(cinetique.get("regime_max"), 1, "tr/min"), False),
            ("Stress Units", "%s / %s" % (number(charge, 0), number(capacite, 0)),
             surcharge),
            ("bras longitudinal",
             "%s (%s, axe %s)" % (number(tangage.get("bras_longitudinal"), 2),
                                  tangage.get("sens", "—"),
                                  tangage.get("axe_longitudinal", "?"))
             if tangage else "—", False),
            ("bras lateral", number(tangage.get("bras_lateral"), 2)
             if tangage else "—", False),
        ]
        # L'assiette REELLE, quand elle est simulee (F3.4) : le bras de levier
        # dit le desequilibre statique, le tangage dit ou le vaisseau en est.
        attitude = report.get("attitude") or {}
        if attitude.get("active"):
            self.instruments.append(
                ("tangage", number(attitude.get("tangage"), 1, "deg"), False))
            self.instruments.append(
                ("roulis", number(attitude.get("roulis"), 1, "deg"), False))
        self.legend = list(overlay.legend)
        self.visible_groups = set(overlay.ranges)
        if overlay.scale > 0:
            self.scale_text = ("echelle : 1 bloc = %s"
                               % number(1.0 / overlay.scale, 0))
        anomalies = report.get("anomalies") or []
        graves = [a for a in anomalies if a.get("gravite") == "grave"]
        self.footer = ("%d anomalie(s), dont %d grave(s)"
                       % (len(anomalies), len(graves))) if anomalies else ""
        self.update()

    # -- rendu -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        self._draw_instruments(painter)
        self._draw_legend(painter)
        painter.end()

    def _panel(self, painter, rect) -> None:
        painter.setBrush(PANEL)
        painter.setPen(QtGui.QPen(BORDER, 1))
        painter.drawRoundedRect(rect, 6, 6)

    def _font(self, painter, size=10, bold=False):
        font = painter.font()
        font.setPointSize(size)
        font.setBold(bold)
        font.setFamily("Consolas")
        painter.setFont(font)
        return QtGui.QFontMetrics(font)

    def _draw_instruments(self, painter) -> None:
        if not self.instruments:
            return
        metrics = self._font(painter, 10)
        label_w = max(metrics.horizontalAdvance(a) for a, _b, _c in self.instruments)
        value_w = max(metrics.horizontalAdvance(b) for _a, b, _c in self.instruments)
        width = self.PAD * 2 + label_w + 18 + value_w
        height = self.PAD * 2 + self.LINE * (len(self.instruments) + 1)
        rect = QtCore.QRectF(self.MARGIN, self.MARGIN, width, height)
        self._panel(painter, rect)

        y = self.MARGIN + self.PAD + self.LINE - 5
        self._font(painter, 10, True)
        painter.setPen(ACCENT)
        painter.drawText(QtCore.QPointF(self.MARGIN + self.PAD, y), self.title)
        self._font(painter, 10)
        for label, value, alert in self.instruments:
            y += self.LINE
            painter.setPen(DIM)
            painter.drawText(QtCore.QPointF(self.MARGIN + self.PAD, y), label)
            painter.setPen(WARN if alert else TEXT)
            painter.drawText(
                QtCore.QPointF(self.MARGIN + width - self.PAD
                               - metrics.horizontalAdvance(value), y), value)

    def _draw_legend(self, painter) -> None:
        if not self.legend:
            return
        rows = []
        for entry in self.legend:
            unit = entry.get("unite", "")
            value = number(entry["intensite"], 1)
            if unit:
                value += " " + unit
            note = ""
            if entry.get("negligeable"):
                note = "  (%d negligeable(s))" % entry["negligeable"]
            rows.append(("%d %s" % (len(rows) + 1, entry["groupe"]),
                         value + note, entry["couleur"],
                         entry["groupe"] in self.visible_groups))

        metrics = self._font(painter, 10)
        label_w = max(metrics.horizontalAdvance(a) for a, _b, _c, _d in rows)
        value_w = max(metrics.horizontalAdvance(b) for _a, b, _c, _d in rows)
        extras = [t for t in (self.scale_text, self.mode, self.footer) if t]
        width = max(self.PAD * 2 + 18 + label_w + 24 + value_w,
                    self.PAD * 2 + max((metrics.horizontalAdvance(t)
                                        for t in extras), default=0))
        height = self.PAD * 2 + self.LINE * (len(rows) + 1 + len(extras))
        rect = QtCore.QRectF(self.MARGIN, self.height() - self.MARGIN - height,
                             width, height)
        self._panel(painter, rect)

        y = rect.top() + self.PAD + self.LINE - 5
        self._font(painter, 10, True)
        painter.setPen(ACCENT)
        painter.drawText(QtCore.QPointF(rect.left() + self.PAD, y), "forces")
        self._font(painter, 10)
        for label, value, color, shown in rows:
            y += self.LINE
            swatch = QtGui.QColor.fromRgbF(*color)
            if not shown:
                swatch.setAlpha(60)
            painter.setBrush(swatch)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(
                QtCore.QRectF(rect.left() + self.PAD, y - 9, 11, 11), 2, 2)
            painter.setPen(TEXT if shown else DIM)
            painter.drawText(QtCore.QPointF(rect.left() + self.PAD + 18, y),
                             label)
            painter.setPen(TEXT if shown else DIM)
            painter.drawText(
                QtCore.QPointF(rect.right() - self.PAD
                               - metrics.horizontalAdvance(value), y), value)
        painter.setPen(DIM)
        for text in extras:
            y += self.LINE
            painter.drawText(QtCore.QPointF(rect.left() + self.PAD, y), text)
