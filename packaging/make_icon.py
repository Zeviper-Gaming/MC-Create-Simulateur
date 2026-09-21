"""Genere l'icone de l'application : assets/createsim.png et assets/createsim.ico.

    python packaging/make_icon.py

Un cube isometrique — le vaisseau — et deux fleches, portance vers le haut et
poids vers le bas : c'est ce que l'outil montre, la decomposition des forces.
Les couleurs sont celles de la vue 3D (portance bleue, poids rouge) rapportees a
un fond sombre ; le cube est bleu-gris comme les blocs.

L'icone est dessinee par le code plutot qu'importee : personne n'a a se demander
d'ou elle vient, ni sous quelle licence, et on la retouche en changeant un nombre.

Le `.ico` regroupe sept tailles, chacune dessinee a sa taille et non reduite
depuis la plus grande : a 16 pixels, une reduction lissee donne une tache.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND = ("#232b38", "#10141b")
TOP, LEFT, RIGHT = "#9bd8ff", "#4a8fc0", "#2c6290"
EDGE = "#0d1117"
LIFT, WEIGHT = "#ffd166", "#ff6b6b"


def _polygon(*points) -> QtGui.QPolygonF:
    return QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points])


def draw(size: int) -> QtGui.QImage:
    """Dessine l'icone dans un carre de `size` pixels, sur une base de 256."""
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(image)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.scale(size / 256.0, size / 256.0)

    gradient = QtGui.QLinearGradient(0, 0, 0, 256)
    gradient.setColorAt(0.0, QtGui.QColor(BACKGROUND[0]))
    gradient.setColorAt(1.0, QtGui.QColor(BACKGROUND[1]))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(QtCore.QRectF(8, 8, 240, 240), 52, 52)

    # le cube : centre (128, 138), demi-diagonale 58
    cx, cy, r = 128.0, 138.0, 58.0
    h = r * 0.5
    top = (cx, cy - r)
    upper_right, lower_right = (cx + r * 0.866, cy - h), (cx + r * 0.866, cy + h)
    bottom = (cx, cy + r)
    lower_left, upper_left = (cx - r * 0.866, cy + h), (cx - r * 0.866, cy - h)
    middle = (cx, cy)

    edge = QtGui.QPen(QtGui.QColor(EDGE), 5.0)
    edge.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(edge)
    for colour, face in ((TOP, (top, upper_right, middle, upper_left)),
                         (LEFT, (upper_left, middle, bottom, lower_left)),
                         (RIGHT, (middle, upper_right, lower_right, bottom))):
        p.setBrush(QtGui.QColor(colour))
        p.drawPolygon(_polygon(*face))

    def arrow(colour: str, tip: tuple, tail: tuple, spread: float) -> None:
        """Une fleche verticale : hampe epaisse, tete triangulaire."""
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(colour))
        direction = 1.0 if tip[1] > tail[1] else -1.0
        head = spread * 1.15
        p.drawRoundedRect(QtCore.QRectF(tail[0] - spread * 0.32, min(tail[1], tip[1] - direction * head),
                                        spread * 0.64, abs(tip[1] - tail[1]) - head * 0.4 + head * 0.4),
                          spread * 0.2, spread * 0.2)
        p.drawPolygon(_polygon((tip[0], tip[1]),
                               (tip[0] - spread, tip[1] - direction * head),
                               (tip[0] + spread, tip[1] - direction * head)))

    arrow(LIFT, tip=(cx, 22.0), tail=(cx, cy - r - 4.0), spread=21.0)
    arrow(WEIGHT, tip=(cx, 236.0), tail=(cx, cy + r + 4.0), spread=19.0)
    p.end()
    return image


def _png(image: QtGui.QImage) -> bytes:
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(path: Path, sizes=SIZES) -> None:
    """Ecrit un .ico dont chaque image est un PNG (Windows Vista et apres)."""
    blobs = [(s, _png(draw(s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for size, blob in blobs:
        dimension = 0 if size >= 256 else size          # 0 signifie 256
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32,
                               len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blob for _s, blob in blobs))


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    draw(256).save(str(ASSETS / "createsim.png"))
    write_ico(ASSETS / "createsim.ico")
    print("icone :", ASSETS / "createsim.png", "et", ASSETS / "createsim.ico")
    return 0


if __name__ == "__main__":
    QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(sys.argv[:1])
    raise SystemExit(main())
