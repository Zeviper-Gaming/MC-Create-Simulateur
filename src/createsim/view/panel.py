"""Bandeau de controle lateral (F4).

Sections repliables, valeurs modifiables en continu, effet visible
immediatement dans la fenetre principale. Aucune validation, aucun bouton
« appliquer ».

PRINCIPE DIRECTEUR : le bandeau n'expose que ce qui existe dans le fichier. Un
vaisseau sans roues n'a pas de section roues. Un bruleur commande par un levier
n'est pas reglable directement — on actionne le levier, et le bruleur suit.
C'est ce qui distingue un simulateur d'un tableur : on pilote le vehicule tel
qu'il est cable, pas ses parametres internes.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..model.kinetics import analog_transmission_ratio
from ..sim.forces import FACING_VEC

MUTED = "color: #9aa2ae;"
STRONG = "color: #e2e6ec;"
ALERT = "color: #ffb060;"
TRAP = "color: #ffd27a;"


def _pos(p) -> str:
    return "%d, %d, %d" % tuple(p)


class EditableName(QtWidgets.QLineEdit):
    """Un nom qu'on change d'un clic gauche.

    « create:analog_lever (14, 13, 20) » ne dit rien de ce que fait le levier ;
    « ballast avant » si. Le champ se lit comme une etiquette tant qu'on n'y
    touche pas, et devient un champ de saisie au clic. Entree valide, Echap
    annule, et un nom vide restaure le libelle par defaut.
    """

    renamed = QtCore.Signal(str)
    clicked = QtCore.Signal()

    def __init__(self, given: str, fallback: str, parent=None):
        super().__init__(given or fallback, parent)
        self.fallback = fallback
        self._before = self.text()
        self.setReadOnly(True)
        self.setFrame(False)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip("clic pour renommer · %s" % fallback)
        self._paint(False)
        self.editingFinished.connect(self._commit)

    def _paint(self, editing: bool) -> None:
        named = self.text() != self.fallback
        color = "#e2e6ec" if named else "#9aa2ae"
        if editing:
            self.setStyleSheet("QLineEdit { background: #1b2027; color: #e2e6ec;"
                               " border: 1px solid #4a90d9; border-radius: 3px; }")
        else:
            self.setStyleSheet("QLineEdit { background: transparent; color: %s;"
                               " border: none; font-weight: %s; }"
                               % (color, "bold" if named else "normal"))

    def set_given(self, given: str) -> None:
        self.setText(given or self.fallback)
        self._paint(False)

    def mousePressEvent(self, event) -> None:
        if self.isReadOnly() and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self._before = self.text()
            self.setReadOnly(False)
            self._paint(True)
            self.selectAll()
            self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if (event.key() == QtCore.Qt.Key.Key_Escape and not self.isReadOnly()):
            self.setText(self._before)
            self.clearFocus()
            return
        super().keyPressEvent(event)

    def _commit(self) -> None:
        if self.isReadOnly():
            return
        self.setReadOnly(True)
        text = self.text().strip()
        if not text or text == self.fallback:
            self.setText(self.fallback)
            text = ""
        self._paint(False)
        self.renamed.emit(text)


class Section(QtWidgets.QWidget):
    """Un volet repliable, comme le bandeau d'Universe Sandbox."""

    def __init__(self, title: str, parent=None, expanded: bool = True):
        super().__init__(parent)
        self.button = QtWidgets.QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(expanded)
        self.button.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; color: #78c8ff;"
            " padding: 4px 2px; text-align: left; }")
        self.button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setArrowType(QtCore.Qt.ArrowType.DownArrow if expanded
                                 else QtCore.Qt.ArrowType.RightArrow)
        self.button.toggled.connect(self._toggle)

        self.body = QtWidgets.QWidget()
        self.form = QtWidgets.QVBoxLayout(self.body)
        self.form.setContentsMargins(8, 2, 4, 8)
        self.form.setSpacing(4)
        self.body.setVisible(expanded)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.button)
        layout.addWidget(self.body)

    def _toggle(self, on: bool) -> None:
        self.body.setVisible(on)
        self.button.setArrowType(QtCore.Qt.ArrowType.DownArrow if on
                                 else QtCore.Qt.ArrowType.RightArrow)

    def add(self, widget) -> None:
        self.form.addWidget(widget)

    def add_row(self, label: str, widget) -> QtWidgets.QLabel:
        row = QtWidgets.QWidget()
        box = QtWidgets.QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        caption = QtWidgets.QLabel(label)
        caption.setStyleSheet(MUTED)
        box.addWidget(caption)
        box.addStretch(1)
        box.addWidget(widget)
        self.form.addWidget(row)
        return caption


class LeverRow(QtWidgets.QFrame):
    """Une commande de bord : un curseur par levier reel du vaisseau (F4.1)."""

    moved = QtCore.Signal(object, int)
    selected = QtCore.Signal(object)
    renamed = QtCore.Signal(object, str)

    def __init__(self, lever, names=None, parent=None):
        super().__init__(parent)
        self.lever = lever
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setStyleSheet("QFrame { border: 1px solid #2a2f38; border-radius: 4px; }")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        kind = lever.block.split(":")[-1].replace("_", " ")
        fallback = "%s · %s" % (kind, _pos(lever.pos))
        given = names.get("levier", lever.pos) if names is not None else ""
        self.head = EditableName(given, fallback)
        self.head.renamed.connect(lambda text: self.renamed.emit(self.lever, text))
        self.head.clicked.connect(lambda: self.selected.emit(self.lever))
        layout.addWidget(self.head)

        line = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 15)
        self.slider.setValue(lever.initial)
        self.slider.valueChanged.connect(self._moved)
        # F4.6 : la valeur numerique est toujours a cote du curseur
        self.value = QtWidgets.QLabel(str(lever.initial))
        self.value.setMinimumWidth(22)
        self.value.setStyleSheet(STRONG)
        line.addWidget(self.slider, 1)
        line.addWidget(self.value)
        layout.addLayout(line)

        self.detail = QtWidgets.QLabel()
        self.detail.setStyleSheet(MUTED)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self._describe(lever.initial)

    def _moved(self, value: int) -> None:
        self.value.setText(str(value))
        self._describe(value)
        self.moved.emit(self.lever.pos, value)

    def _describe(self, signal: int) -> None:
        cibles = len(self.lever.targets)
        text = "commande %d organe(s)" % cibles if cibles else "ne commande rien"
        # Le piege que le cahier demande de lever, et qu'une mesure en jeu a
        # deplace : ce n'est pas le levier qui ment sur son cran, c'est son
        # DESTINATAIRE qui lit l'echelle a l'envers. Deux manettes voisines sur
        # la meme console ne vont pas dans le meme sens.
        note = self.lever.ENDS.get(self.lever.scale or "")
        if self.lever.scale in ("inverse", "mixte"):
            self.detail.setStyleSheet(TRAP)
            text = "cran %d · %s · %s" % (signal, note, text)
        else:
            self.detail.setStyleSheet(MUTED)
            if note:
                text = "cran %d · %s · %s" % (signal, note, text)
        self.detail.setText(text)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.lever)
        super().mousePressEvent(event)


class ControlPanel(QtWidgets.QScrollArea):
    """Le bandeau complet. Ne construit que les sections qui ont un objet."""

    commands_changed = QtCore.Signal()
    situation_changed = QtCore.Signal()
    selection_changed = QtCore.Signal(object)
    sim_action = QtCore.Signal(str)
    renamed = QtCore.Signal()

    def __init__(self, model, sim, parent=None):
        super().__init__(parent)
        self.model = model
        self.sim = sim
        self.setWidgetResizable(True)
        self.setMinimumWidth(330)
        self.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QtWidgets.QWidget()
        self.column = QtWidgets.QVBoxLayout(container)
        self.column.setContentsMargins(6, 6, 6, 6)
        self.column.setSpacing(6)
        self.setWidget(container)

        self._burner_rows: list[tuple] = []
        self._transmission_rows: list[tuple] = []
        self._propulsion_rows: list[tuple] = []
        self._pocket_rows: list[tuple] = []
        self._nameplates: list[tuple] = []

        self._build_simulation()
        self._build_levers()
        self._build_burners()
        self._build_transmissions()
        self._build_propulsion()
        self._build_situation()
        self.column.addStretch(1)
        self.refresh()

    # -- nommage -----------------------------------------------------------
    def _nameplate(self, kind: str, identifier, fallback: str) -> "EditableName":
        """Une etiquette renommable d'un clic, persistee a cote du vaisseau."""
        plate = EditableName(self.model.names.get(kind, identifier), fallback)
        plate.renamed.connect(
            lambda text, k=kind, i=identifier: self._rename(k, i, text))
        self._nameplates.append((kind, identifier, plate))
        return plate

    def _rename(self, kind: str, identifier, text: str) -> None:
        self.model.names.set(kind, identifier, text)
        self.renamed.emit()

    # -- sections ----------------------------------------------------------
    def _section(self, title: str, expanded: bool = True) -> Section:
        section = Section(title, expanded=expanded)
        self.column.addWidget(section)
        return section

    def _build_simulation(self) -> None:
        section = self._section("Simulation")
        bar = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        self.play = QtWidgets.QToolButton()
        self.play.setText("▶")
        self.play.setCheckable(True)
        self.play.setToolTip("marche / pause")
        self.play.toggled.connect(
            lambda on: self.sim_action.emit("play" if on else "pause"))
        row.addWidget(self.play)
        step = QtWidgets.QToolButton()
        step.setText("⏭")
        step.setToolTip("avancer d'un tick")
        step.clicked.connect(lambda: self.sim_action.emit("step"))
        row.addWidget(step)
        # F2.4 : pause, 1x, 4x, 16x, et avance d'un tick
        self.speeds = QtWidgets.QButtonGroup(self)
        for factor in (1, 4, 16):
            button = QtWidgets.QToolButton()
            button.setText("×%d" % factor)
            button.setCheckable(True)
            button.setChecked(factor == 1)
            button.clicked.connect(
                lambda _c=False, f=factor: self.sim_action.emit("speed:%d" % f))
            self.speeds.addButton(button, factor)
            row.addWidget(button)
        row.addStretch(1)
        reset = QtWidgets.QToolButton()
        reset.setText("remise a zero")
        reset.setToolTip("jette l'etat, garde le modele")
        reset.clicked.connect(lambda: self.sim_action.emit("reset"))
        row.addWidget(reset)
        section.add(bar)

        self.static = QtWidgets.QPushButton("converger vers l'equilibre")
        self.static.setToolTip("mode statique : saute le transitoire (F2.7)")
        self.static.clicked.connect(lambda: self.sim_action.emit("static"))
        section.add(self.static)

        self.clock = QtWidgets.QLabel()
        self.clock.setStyleSheet(MUTED)
        section.add(self.clock)

    def _build_levers(self) -> None:
        levers = self.model.organ("redstone").levers
        if not levers:
            return
        section = self._section("Commandes de bord")
        self.lever_rows = []
        for lever in levers:
            row = LeverRow(lever, self.model.names)
            row.moved.connect(self._lever_moved)
            row.selected.connect(self.selection_changed.emit)
            row.renamed.connect(
                lambda lv, text: self._rename("levier", lv.pos, text))
            section.add(row)
            self.lever_rows.append(row)

    def _build_burners(self) -> None:
        organ = self.model.organ("ballons")
        if not organ.burners:
            return
        redstone = self.model.organ("redstone")
        section = self._section("Groupes de bruleurs")

        groups: dict[tuple, list] = {}
        for burner in organ.burners:
            key = redstone.channel_of.get(burner["pos"], ("sans canal", ""))
            groups.setdefault(key, []).append(burner)

        for key, burners in groups.items():
            name = " / ".join(part.split(":")[-1] for part in key if part)
            title = self._nameplate(
                "canal", name, "canal %s — %d bruleur(s)" % (name, len(burners)))
            section.add(title)
            status = QtWidgets.QLabel()
            status.setStyleSheet(MUTED)
            status.setWordWrap(True)
            section.add(status)
            for burner in burners:
                spin = QtWidgets.QSpinBox()
                spin.setRange(0, 20000)
                spin.setSingleStep(25)
                spin.setValue(int(burner["reglage"]))
                spin.setSuffix(" m³")
                spin.valueChanged.connect(
                    lambda v, b=burner: self._scroll_changed(b, v))
                section.add_row("reglage molette %s" % _pos(burner["pos"]), spin)
            self._burner_rows.append((key, burners, status))

        for index, pocket in enumerate(organ.pockets):
            section.add(self._nameplate("poche", index, "poche %d" % (index + 1)))
            label = QtWidgets.QLabel()
            label.setStyleSheet(MUTED)
            label.setWordWrap(True)
            section.add(label)
            self._pocket_rows.append((index, pocket, label))

    def _build_transmissions(self) -> None:
        kin = self.model.organ("cinetique")
        positions = sorted(p for p, b in kin.nodes.items()
                           if b["name"] == "simulated:analog_transmission")
        if not positions:
            return
        section = self._section("Transmissions", expanded=False)
        for pos in positions:
            section.add(self._nameplate("transmission", pos,
                                        "transmission · %s" % _pos(pos)))
            label = QtWidgets.QLabel()
            label.setStyleSheet(MUTED)
            label.setWordWrap(True)
            section.add(label)
            self._transmission_rows.append((pos, label))

    def _build_propulsion(self) -> None:
        bearings = self.model.organ("paliers").of_type(
            "aeronautics:propeller_bearing")
        wheels = sorted(self.model.structure.positions_of("offroad:wheel_mount"))
        if not bearings and not wheels:
            return
        section = self._section("Propulsion")
        for bearing in bearings:
            section.add(self._nameplate("palier", bearing.pos,
                                        "helice · %s" % _pos(bearing.pos)))
            label = QtWidgets.QLabel()
            label.setStyleSheet(MUTED)
            label.setWordWrap(True)
            section.add(label)
            self._propulsion_rows.append((bearing, label))
        if wheels:
            caption = QtWidgets.QLabel("%d roue(s) motrice(s)" % len(wheels))
            caption.setStyleSheet(MUTED)
            section.add(caption)

    def _build_situation(self) -> None:
        section = self._section("Situation")
        options = self.sim.options

        self.altitude = QtWidgets.QDoubleSpinBox()
        self.altitude.setRange(-64.0, 320.0)
        self.altitude.setDecimals(1)
        self.altitude.setValue(options.altitude)
        self.altitude.setSuffix(" m")
        self.altitude.valueChanged.connect(self._altitude_changed)
        section.add_row("altitude", self.altitude)

        self.pressure = QtWidgets.QLabel()
        self.pressure.setStyleSheet(MUTED)
        section.add_row("pression (lecture seule)", self.pressure)

        self.ground = QtWidgets.QCheckBox("plan de sol")
        self.ground.setChecked(options.ground_enabled)
        self.ground.toggled.connect(self._ground_changed)
        section.add(self.ground)

        self.ground_y = QtWidgets.QDoubleSpinBox()
        self.ground_y.setRange(-64.0, 320.0)
        self.ground_y.setValue(options.ground_altitude)
        self.ground_y.valueChanged.connect(self._ground_changed)
        section.add_row("altitude du sol", self.ground_y)

        self.friction = QtWidgets.QDoubleSpinBox()
        self.friction.setRange(0.0, 2.0)
        self.friction.setSingleStep(0.05)
        self.friction.setValue(options.ground_friction)
        self.friction.valueChanged.connect(self._ground_changed)
        section.add_row("friction du sol", self.friction)

        # F4.7 : les constantes restent modifiables, en signalant l'ecart
        self.expert = QtWidgets.QCheckBox("mode expert (constantes du jeu)")
        self.expert.toggled.connect(self._expert_changed)
        section.add(self.expert)

        tables = self.model.tables
        self.gravity = QtWidgets.QDoubleSpinBox()
        self.gravity.setRange(0.0, 60.0)
        self.gravity.setSingleStep(0.5)
        self.gravity.setValue(tables.get("pressure.gravity"))
        self.gravity.setEnabled(False)
        self.gravity.valueChanged.connect(
            lambda v: self._override("pressure.gravity", v))
        section.add_row("gravite", self.gravity)

        self.hot_air = QtWidgets.QDoubleSpinBox()
        self.hot_air.setRange(0.0, 20.0)
        self.hot_air.setSingleStep(0.1)
        self.hot_air.setValue(tables.get("forces.hot_air_strength"))
        self.hot_air.setEnabled(False)
        self.hot_air.valueChanged.connect(
            lambda v: self._override("forces.hot_air_strength", v))
        section.add_row("air chaud (kg/m³)", self.hot_air)

        self.taint = QtWidgets.QLabel()
        self.taint.setStyleSheet(ALERT)
        self.taint.setWordWrap(True)
        section.add(self.taint)

        # F4.5 : sauvegarde et rappel de jeux de reglages nommes
        saved = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(saved)
        row.setContentsMargins(0, 0, 0, 0)
        self.presets = QtWidgets.QComboBox()
        self.presets.setEditable(True)
        row.addWidget(self.presets, 1)
        store = QtWidgets.QToolButton()
        store.setText("garder")
        store.clicked.connect(self._save_preset)
        row.addWidget(store)
        recall = QtWidgets.QToolButton()
        recall.setText("rappeler")
        recall.clicked.connect(self._load_preset)
        row.addWidget(recall)
        section.add_row("jeux de reglages", saved)
        self._refresh_presets()

    # -- reactions ---------------------------------------------------------
    def _lever_moved(self, pos, value: int) -> None:
        self.sim.set_command(pos, value)
        self.commands_changed.emit()

    def _scroll_changed(self, burner, value: int) -> None:
        """Le reglage molette est un parametre de CONCEPTION, pas une commande
        de vol : il se regle ici, et le fichier source n'est jamais ecrit."""
        burner["reglage"] = float(value)
        block = self.model.structure.blocks.get(burner["pos"])
        if block is not None:
            block.setdefault("nbt", {})["ScrollValue"] = value
        self.commands_changed.emit()

    def _altitude_changed(self, value: float) -> None:
        # F4.4 : modifiable simulation en cours
        self.sim.options.altitude = value
        self.sim.state.position[1] = value
        self.situation_changed.emit()

    def _ground_changed(self, *_args) -> None:
        from ..sim.atmosphere import FlatGround, NoGround
        options = self.sim.options
        options.ground_enabled = self.ground.isChecked()
        options.ground_altitude = self.ground_y.value()
        options.ground_friction = self.friction.value()
        self.sim.ground = (FlatGround(options.ground_altitude,
                                      options.ground_friction, True)
                           if options.ground_enabled else NoGround())
        self.situation_changed.emit()

    def _expert_changed(self, on: bool) -> None:
        tables = self.model.tables
        tables.expert_mode = on
        if not on:
            tables.clear_overrides()
            self.gravity.blockSignals(True)
            self.hot_air.blockSignals(True)
            self.gravity.setValue(tables.get("pressure.gravity"))
            self.hot_air.setValue(tables.get("forces.hot_air_strength"))
            self.gravity.blockSignals(False)
            self.hot_air.blockSignals(False)
        self.gravity.setEnabled(on)
        self.hot_air.setEnabled(on)
        self.situation_changed.emit()

    def _override(self, key: str, value: float) -> None:
        tables = self.model.tables
        if tables.expert_mode:
            tables.override(key, float(value))
            self.situation_changed.emit()

    # -- jeux de reglages ---------------------------------------------------
    def _preset_path(self) -> Path:
        source = Path(self.model.structure.path or "reglages.nbt")
        return source.with_suffix(".reglages.json")

    def _read_presets(self) -> dict:
        path = self._preset_path()
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _refresh_presets(self) -> None:
        self.presets.blockSignals(True)
        current = self.presets.currentText()
        self.presets.clear()
        self.presets.addItems(sorted(self._read_presets()))
        self.presets.setCurrentText(current)
        self.presets.blockSignals(False)

    def _save_preset(self) -> None:
        name = self.presets.currentText().strip()
        if not name:
            return
        data = self._read_presets()
        data[name] = {
            "commandes": {",".join(map(str, p)): v
                          for p, v in self.sim.state.commands.items()},
            "molettes": {",".join(map(str, b["pos"])): b["reglage"]
                         for b in self.model.organ("ballons").burners},
            "altitude": self.sim.options.altitude,
        }
        try:
            self._preset_path().write_text(
                json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            return
        self._refresh_presets()

    def _load_preset(self) -> None:
        entry = self._read_presets().get(self.presets.currentText().strip())
        if not entry:
            return
        for key, value in (entry.get("commandes") or {}).items():
            pos = tuple(int(v) for v in key.split(","))
            self.sim.set_command(pos, int(value))
        for row in getattr(self, "lever_rows", []):
            row.slider.blockSignals(True)
            row.slider.setValue(self.sim.state.commands.get(row.lever.pos,
                                                            row.lever.initial))
            row.slider.blockSignals(False)
            row._describe(row.slider.value())
        for burner in self.model.organ("ballons").burners:
            key = ",".join(map(str, burner["pos"]))
            if key in (entry.get("molettes") or {}):
                burner["reglage"] = float(entry["molettes"][key])
        if "altitude" in entry:
            self.altitude.setValue(float(entry["altitude"]))
        self.commands_changed.emit()

    # -- rafraichissement ---------------------------------------------------
    def refresh(self) -> None:
        """Remet a jour toutes les valeurs en lecture seule."""
        sim, state = self.sim, self.sim.state
        self.clock.setText("tick %d · %.2f s · altitude %.2f · vitesse %.2f blocs/s"
                           % (state.tick, state.seconds, state.altitude,
                              state.speed))
        self.pressure.setText("%.4f" % state.pressure)

        organ = self.model.organ("ballons")
        for key, burners, label in self._burner_rows:
            signal = max((state.signals.get(b["pos"], b["signal"])
                          for b in burners), default=0)
            demande = sum(b["reglage"] * signal / 15.0 for b in burners)
            label.setText("signal recu %d/15 · sortie %.0f m³ sur %.0f demandes"
                          % (signal, demande,
                             sum(b["reglage"] for b in burners)))

        for index, pocket, label in self._pocket_rows:
            gas = state.gas[index] if index < len(state.gas) else 0.0
            capacity = max(pocket.capacity, 1)
            note = " — SATUREE" if pocket.max_demand > pocket.capacity else ""
            label.setText("poche %d : %.0f / %d m³ (%.0f %%)%s"
                          % (index + 1, gas, pocket.capacity,
                             100.0 * gas / capacity, note))

        for pos, label in self._transmission_rows:
            block = self.model.organ("cinetique").nodes.get(pos, {})
            nbt = block.get("nbt") or {}
            signal = int(state.signals.get(pos, nbt.get("Signal", 0) or 0))
            ratio = analog_transmission_ratio(signal)
            if ratio["mode"] == "decouple":
                # Le cahier l'exige en toutes lettres : c'est le piege le plus
                # couteux, et il est invisible en jeu.
                text = "%s · signal %d · DECOUPLE, rien ne passe" % (_pos(pos),
                                                                     signal)
                label.setStyleSheet(TRAP)
            else:
                text = ("%s · signal %d · %s · reduction %.3f, augmentation %.2f"
                        % (_pos(pos), signal, ratio["mode"],
                           ratio["reduction"], ratio["augmentation"]))
                label.setStyleSheet(MUTED)
            label.setText(text)

        thrust_total = 0.0
        thrusts = []
        coef = self.model.tables.get("forces.propeller_bearing_thrust")
        exponent = self.model.tables.get("forces.propeller_sail_exponent")
        for bearing, _label in self._propulsion_rows:
            rpm = abs(state.speeds.get(bearing.pos, 0.0))
            thrust = (bearing.sails ** exponent) * rpm * coef if bearing.sails else 0.0
            thrusts.append((rpm, thrust))
            thrust_total += thrust
        for (bearing, label), (rpm, thrust) in zip(self._propulsion_rows, thrusts):
            share = (100.0 * thrust / thrust_total) if thrust_total else 0.0
            voiles = "rotor assemble" if bearing.assembled else "%d voile(s)" % bearing.sails
            label.setText("%s · %s · %.1f tr/min · poussee %.0f (%.0f %%)"
                          % (_pos(bearing.pos), voiles, rpm, thrust, share))

        tables = self.model.tables
        if tables.tainted:
            self.taint.setText(
                "MODE EXPERT : %s ne reposent plus sur les constantes du jeu"
                % ", ".join(tables.tainted_keys))
        else:
            self.taint.setText("")
