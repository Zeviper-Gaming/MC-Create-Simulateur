"""Barre de coupe : ouvrir la coque par un plan mobile (F3.3).

Un vaisseau Create est plein. Vu de l'exterieur on ne voit qu'une carene, et
tout ce que le simulateur a a dire — ou sont les brûleurs, comment la poche de
gaz remplit la coque, ou passe l'arbre cinetique — est dessous. La coupe est
donc un instrument d'inspection, pas un effet : elle enleve une moitie du
vaisseau pour montrer l'autre.

Le plan vit dans le repere du VAISSEAU. Quand la coque pique du nez, la coupe
pique avec elle : on continue de regarder la meme cloison. Un plan fixe dans le
monde donnerait l'inverse — la coupe glisserait le long du vaisseau des qu'il
bouge, et on ne saurait plus ce qu'on regarde.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

#: noms des axes tels que le cahier les emploie
AXES = (("X — travers", 0), ("Y — hauteur", 1), ("Z — long", 2))


class CutBar(QtWidgets.QWidget):
    """Choisir un axe, faire glisser le plan, retourner le sens."""

    #: (axe 0/1/2 ou None si la coupe est fermee, position en blocs, sens)
    changed = QtCore.Signal(object, float, bool)

    def __init__(self, size, parent=None):
        super().__init__(parent)
        self.size_blocks = tuple(int(v) for v in size)

        self.axis = QtWidgets.QComboBox()
        self.axis.addItem("aucune", None)
        for label, index in AXES:
            self.axis.addItem(label, index)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(max(self.size_blocks))
        self.slider.setEnabled(False)

        self.reverse = QtWidgets.QToolButton()
        self.reverse.setText("sens")
        self.reverse.setCheckable(True)
        self.reverse.setEnabled(False)
        self.reverse.setToolTip("Garder l'autre moitie")

        self.readout = QtWidgets.QLabel("—")
        self.readout.setMinimumWidth(68)

        # Aucun de ces widgets ne prend le clavier : les fleches deplacent le
        # bloc selectionne (F6.2), et une coupe qui capterait le focus au
        # premier clic volerait le geste d'edition sans prevenir.
        for widget in (self.axis, self.slider, self.reverse):
            widget.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        box = QtWidgets.QHBoxLayout(self)
        box.setContentsMargins(8, 3, 8, 3)
        box.setSpacing(8)
        box.addWidget(QtWidgets.QLabel("Coupe"))
        box.addWidget(self.axis)
        box.addWidget(self.slider, 1)
        box.addWidget(self.readout)
        box.addWidget(self.reverse)

        self.axis.currentIndexChanged.connect(self._axis_changed)
        self.slider.valueChanged.connect(self._emit)
        self.reverse.toggled.connect(self._emit)

    # -- etat ---------------------------------------------------------------
    def state(self):
        """(axe, position, sens) — l'axe vaut `None` quand rien n'est coupe."""
        axis = self.axis.currentData()
        return axis, float(self.slider.value()), self.reverse.isChecked()

    def _axis_changed(self) -> None:
        axis = self.axis.currentData()
        live = axis is not None
        self.slider.setEnabled(live)
        self.reverse.setEnabled(live)
        if live:
            extent = self.size_blocks[axis]
            self.slider.setMaximum(extent)
            # On ouvre a mi-coque : c'est la coupe qu'on veut neuf fois sur dix,
            # et une coupe qui demarre a 0 n'affiche rien du tout.
            self.slider.blockSignals(True)
            self.slider.setValue(extent // 2)
            self.slider.blockSignals(False)
        self._emit()

    def _emit(self) -> None:
        axis, offset, reverse = self.state()
        if axis is None:
            self.readout.setText("—")
        else:
            self.readout.setText("%s %s %d" % ("xyz"[axis],
                                               "≥" if reverse else "≤",
                                               int(offset)))
        self.changed.emit(axis, offset, reverse)
