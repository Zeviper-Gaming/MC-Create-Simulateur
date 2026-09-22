"""L'edition dans la fenetre : le bloc selectionne, les gestes, le diff (L5).

Deux widgets, parce qu'ils n'ont pas la meme vie.

`EditorPanel`, dans un onglet : le bloc clique (nom, position, proprietes
editables — F6.1), les quatre gestes (F6.2), la pile d'annulation (F6.5),
l'export (F6.7), et le drapeau de fiabilite des voiles apres une edition pres
d'un palier (F6.9).

`DiffInset`, sous les onglets, toujours visible : le cahier le veut PERMANENT
(F6.6). Une variante s'affiche par rapport a l'etat charge, jamais dans
l'absolu — et un encart qu'il faut aller chercher dans un onglet n'est pas lu.

Aucun des deux ne touche au modele. Ils emettent `gesture(nom, argument)` ;
la fenetre execute, rattrape les refus (« superposition refusee ») et
rafraichit. La logique d'edition reste en un seul endroit, testee sans Qt.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .panel import MUTED, STRONG, TRAP, Section

GOOD = "color: #6fd49a;"
BAD = "color: #ff8a7a;"

#: pour chaque grandeur du diff, le sens qui est une amelioration
BETTER_WHEN = {
    "masse": -1, "portance max": +1, "marge SU": +1,
    "vitesse de pointe": +1, "altitude d'equilibre": +1,
}

MOVES = (("x−", (-1, 0, 0)), ("x+", (1, 0, 0)), ("y−", (0, -1, 0)),
         ("y+", (0, 1, 0)), ("z−", (0, 0, -1)), ("z+", (0, 0, 1)))


def _fmt(value) -> str:
    if value is None:
        return "—"
    if value == float("inf"):
        return "∞"
    if abs(value) >= 1000:
        return "%.0f" % value
    return "%.2f" % value


class DiffInset(QtWidgets.QFrame):
    """L'ecart signe de chaque grandeur, contre l'etat charge (F6.6)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame { border-top: 1px solid #2a2f38; }")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        self.title = QtWidgets.QLabel()
        self.title.setStyleSheet("color: #78c8ff; font-weight: bold; border: none;")
        layout.addWidget(self.title)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(1)
        layout.addLayout(self.grid)
        self._rows: list[tuple[QtWidgets.QLabel, ...]] = []
        self.set_deltas(None)

    def set_deltas(self, deltas, edits: int = 0) -> None:
        """`None` : aucune edition — l'encart le dit au lieu de disparaitre,
        un panneau qui change de forme selon l'etat se relit mal."""
        for row in self._rows:
            for label in row:
                self.grid.removeWidget(label)
                label.deleteLater()
        self._rows = []
        if not deltas:
            self.title.setText("Variante : état chargé, aucune édition")
            return
        self.title.setText("Variante : %d édition(s), écart à l'état chargé"
                           % edits)
        for row, delta in enumerate(deltas):
            name = QtWidgets.QLabel(delta.nom)
            name.setStyleSheet(MUTED + " border: none;")
            before = QtWidgets.QLabel(_fmt(delta.avant))
            after = QtWidgets.QLabel(_fmt(delta.apres))
            for label in (before, after):
                label.setStyleSheet(STRONG + " border: none;")
                label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            gap = QtWidgets.QLabel(self._gap_text(delta))
            gap.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            gap.setStyleSheet(self._gap_style(delta) + " border: none;")
            for col, label in enumerate((name, before, after, gap)):
                self.grid.addWidget(label, row, col)
            self._rows.append((name, before, after, gap))

    @staticmethod
    def _gap_text(delta) -> str:
        if delta.sans_objet:
            return "sans objet"
        if delta.absent:
            return "apparaît" if delta.avant is None else "disparaît"
        if not delta.bouge:
            return "="
        ecart = delta.ecart
        text = ("%+.2f" % ecart if abs(ecart) >= 0.01 else "%+.4f" % ecart)
        if delta.relatif is not None:
            percent = 100 * delta.relatif
            text += ("  (%+.1f %%)" % percent if abs(percent) >= 0.1
                     else "  (%+.3f %%)" % percent)
        return text

    @staticmethod
    def _gap_style(delta) -> str:
        sense = BETTER_WHEN.get(delta.nom)
        if not delta.bouge or delta.absent or sense is None or not delta.ecart:
            return MUTED
        return GOOD if delta.ecart * sense > 0 else BAD


class EditorPanel(QtWidgets.QScrollArea):
    """Le bloc selectionne et ce qu'on peut en faire."""

    #: (geste, argument) — la fenetre execute, ce panneau ne touche a rien
    gesture = QtCore.Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(6)
        self.setWidget(body)

        self.pos = None
        self.normal = None

        # --- le bloc (F6.1) ---
        block = Section("Bloc sélectionné")
        self.name = QtWidgets.QLabel()
        self.name.setStyleSheet(STRONG + " font-weight: bold;")
        self.name.setWordWrap(True)
        self.where = QtWidgets.QLabel()
        self.where.setStyleSheet(MUTED)
        self.where.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        block.add(self.name)
        block.add(self.where)
        self.props_box = QtWidgets.QWidget()
        self.props_form = QtWidgets.QFormLayout(self.props_box)
        self.props_form.setContentsMargins(0, 2, 0, 2)
        block.add(self.props_box)
        self.bearing_note = QtWidgets.QLabel()
        self.bearing_note.setWordWrap(True)
        block.add(self.bearing_note)
        column.addWidget(block)

        # --- les gestes (F6.2) ---
        gestures = Section("Gestes")
        self.delete = QtWidgets.QPushButton("Supprimer le bloc  (Suppr)")
        self.delete.clicked.connect(
            lambda: self.pos and self.gesture.emit("supprimer", self.pos))
        gestures.add(self.delete)

        caption = QtWidgets.QLabel("Déplacer d'une case  (flèches, PgPréc, PgSuiv)")
        caption.setStyleSheet(MUTED)
        caption.setWordWrap(True)
        gestures.add(caption)
        move_row = QtWidgets.QWidget()
        move_box = QtWidgets.QHBoxLayout(move_row)
        move_box.setContentsMargins(0, 0, 0, 0)
        move_box.setSpacing(2)
        self.move_buttons = []
        for label, step in MOVES:
            button = QtWidgets.QToolButton()
            button.setText(label)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                 QtWidgets.QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _c=False, s=step: self._move(s))
            move_box.addWidget(button)
            self.move_buttons.append(button)
        gestures.add(move_row)

        self.palette = QtWidgets.QComboBox()
        self.palette.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.palette.setMinimumContentsLength(12)
        self.palette.setToolTip("palette restreinte aux types de blocs deja "
                                "presents dans le fichier charge")
        self.add = QtWidgets.QPushButton("Poser contre la face")
        self.add.setToolTip("pose le type choisi contre la face cliquee du "
                            "bloc selectionne, comme en jeu")
        self.add.clicked.connect(self._add)
        gestures.add(self.palette)
        gestures.add(self.add)
        column.addWidget(gestures)

        # --- la pile (F6.5) et l'export (F6.7) ---
        history = Section("Variante")
        self.history = QtWidgets.QLabel()
        self.history.setStyleSheet(MUTED)
        history.add(self.history)
        row = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        self.undo = QtWidgets.QPushButton("Annuler")
        self.redo = QtWidgets.QPushButton("Refaire")
        self.revert = QtWidgets.QPushButton("Original")
        self.revert.setToolTip("retour a l'original en une commande")
        for button, name in ((self.undo, "annuler"), (self.redo, "refaire"),
                             (self.revert, "original")):
            button.clicked.connect(lambda _c=False, n=name: self.gesture.emit(n, None))
            box.addWidget(button)
        history.add(row)
        self.export = QtWidgets.QPushButton("Exporter la variante en .nbt…")
        self.export.setToolTip("un fichier NOUVEAU, nomme et horodate : le "
                               "fichier source n'est jamais ecrit")
        self.export.clicked.connect(lambda: self.gesture.emit("exporter", None))
        history.add(self.export)
        warning = QtWidgets.QLabel(
            "Une variante qui va bien à l'écran ne tient pas forcément en "
            "jeu : colle, châssis et attaches de Create ne sont pas vérifiés.")
        warning.setWordWrap(True)
        warning.setStyleSheet(MUTED + " font-style: italic;")
        history.add(warning)
        column.addWidget(history)
        column.addStretch(1)

        self.show_block(None, None)
        self.set_history(0, 0)

    # -- ce que la fenetre lui dit ------------------------------------------
    def set_palette(self, names) -> None:
        current = self.palette.currentText()
        self.palette.blockSignals(True)
        self.palette.clear()
        self.palette.addItems(list(names))
        if current:
            self.palette.setCurrentText(current)
        self.palette.blockSignals(False)

    def set_history(self, edits: int, redo: int) -> None:
        self.undo.setEnabled(edits > 0)
        self.revert.setEnabled(edits > 0)
        self.redo.setEnabled(redo > 0)
        self.export.setEnabled(True)
        self.history.setText(
            "état chargé" if not edits else
            "%d édition(s) · %d à refaire" % (edits, redo))

    def show_block(self, pos, entry, choices=None, normal=None,
                   bearing_note: str | None = None) -> None:
        """Affiche le bloc clique. `choices(nom, cle)` donne les valeurs
        proposees pour chaque propriete."""
        self.pos = tuple(pos) if pos is not None else None
        self.normal = tuple(normal) if normal is not None else None
        while self.props_form.rowCount():
            self.props_form.removeRow(0)
        selected = pos is not None and entry is not None
        for widget in [self.delete, self.add] + self.move_buttons:
            widget.setEnabled(selected)
        # F6.9 AVANT le reste : c'est souvent apres une suppression — donc sans
        # bloc selectionne — qu'on veut lire le drapeau du palier voisin.
        self.bearing_note.setText(bearing_note or "")
        self.bearing_note.setStyleSheet(TRAP if bearing_note and (
            "incertain" in bearing_note or "majorant" in bearing_note) else MUTED)
        if not selected:
            self.name.setText("Aucun bloc")
            self.where.setText("clic sur le vaisseau pour en choisir un")
            return
        self.name.setText(entry["name"])
        face = ("" if normal is None else
                "  ·  face %s" % _face_name(normal))
        self.where.setText("position %d, %d, %d%s" % (tuple(pos) + (face,)))
        for key, value in sorted((entry.get("props") or {}).items()):
            combo = QtWidgets.QComboBox()
            values = list(choices(entry["name"], key)) if choices else [value]
            if value not in values:
                values.append(value)
            combo.addItems(values)
            combo.setCurrentText(value)
            combo.currentTextChanged.connect(
                lambda text, k=key: self.gesture.emit(
                    "propriete", (self.pos, k, text)))
            self.props_form.addRow(key, combo)

    # -- gestes -------------------------------------------------------------
    def _move(self, step) -> None:
        if self.pos is None:
            return
        target = tuple(self.pos[i] + step[i] for i in range(3))
        self.gesture.emit("deplacer", (self.pos, target))

    def _add(self) -> None:
        if self.pos is None or not self.palette.currentText():
            return
        normal = self.normal or (0, 1, 0)
        target = tuple(self.pos[i] + normal[i] for i in range(3))
        self.gesture.emit("poser", (target, self.palette.currentText()))


def _face_name(normal) -> str:
    names = {(1, 0, 0): "x+", (-1, 0, 0): "x−", (0, 1, 0): "dessus",
             (0, -1, 0): "dessous", (0, 0, 1): "z+", (0, 0, -1): "z−"}
    return names.get(tuple(normal), "?")
