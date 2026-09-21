"""Fenetre de L2 : actionner les commandes et voir le vaisseau reagir.

C'est le perimetre demande par le cahier — le minimum vendable. La vue 3D de
L1 montre toujours la decomposition des forces, mais elle vit maintenant : un
bandeau lateral expose les commandes reelles du vaisseau, et une boucle a
1/20 s fait avancer la simulation.

Le bandeau n'expose que ce qui existe dans le fichier. On pilote le vehicule
tel qu'il est cable, pas ses parametres internes.
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..model.vehicle import VehicleModel
from ..sim.forces import lift_centre, resultant, torque_about
from ..sim.compare import compare
from ..sim.scenario import Recorder, Scenario, default_library
from ..sim.state import SimOptions
from ..sim.tick import Simulation
from ..sim.telemetry import Trace
from .cubes import CubeView, default_format
from .curves import CurvePanel
from .diagnostics import DiagnosticsPanel
from .hud import Hud
from .menus import fill_recent, install_menus
from .mesh import (build_cells_mesh, build_kinetic_mesh, build_marked_mesh,
                   build_mesh, families_from_model)
from .panel import ControlPanel
from .vectors import build_force_overlay

#: teinte des poches de gaz, du vide au plein (F3.11)
POCKET_EMPTY = (0.42, 0.46, 0.55)
POCKET_FULL = (0.40, 0.78, 1.00)

#: surbrillance d'une commande selectionnee et de ses destinataires (F4.3)
SELECTED_COLOR = (1.00, 0.92, 0.35)
TARGET_COLOR = (0.40, 1.00, 0.70)
#: surbrillance des blocs d'une anomalie (F5)
ANOMALY_COLOR = (1.00, 0.42, 0.38)

TICK_MS = 50

HELP = ("souris : orbite, molette : zoom, clic droit : translation   |   "
        "1-9 filtre une force, F toutes, B le gaz, K le regime   |   "
        "A avant, C cote, H dessus, P arriere, I iso, R recadrer")


class VehicleWindow(QtWidgets.QMainWindow):
    """Vue 3D a gauche, bandeau de controle a droite, boucle au milieu."""

    #: ouvrir un autre vaisseau — c'est le lanceur qui s'en charge, la fenetre
    #: ne sait ni ou sont les fichiers ni comment remplacer sa propre session
    open_requested = QtCore.Signal(str)
    browse_requested = QtCore.Signal()
    about_requested = QtCore.Signal()

    def __init__(self, model: VehicleModel, sim: Simulation):
        super().__init__()
        self.model = model
        self.sim = sim
        self.speed = 1
        self.name = (model.structure.path or "").replace("\\", "/").split("/")[-1]
        self.setWindowTitle("createsim — %s" % self.name)
        self._recent_menu = install_menus(self)

        self.mesh = build_mesh(model.structure, families_from_model(model))
        overlay = self._overlay()
        # La geometrie des poches est calculee UNE fois : elle ne change qu'a
        # l'edition d'un bloc. La refaire a chaque tick coutait 33 ms et
        # ramenait la boucle sous le seuil des 20 ticks/s.
        self._pocket_meshes = self._build_pocket_meshes()
        self.view = CubeView(self.mesh, overlay, self._pocket_meshes,
                             self._kinetic_mesh())
        self.overlay_data = overlay

        self.panel = ControlPanel(model, sim)
        self.diagnostics = DiagnosticsPanel()
        self.curves = CurvePanel()
        self.trace = Trace()
        self.trace.record(sim)
        self.curves.set_trace(self.trace)
        self.replay: Trace | None = None

        left = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        left.addWidget(self.view)
        left.addWidget(self.curves)
        left.setStretchFactor(0, 1)
        left.setStretchFactor(1, 0)
        left.setSizes([540, 190])

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.panel, "Commandes")
        self.tabs.addTab(self.diagnostics, "Diagnostic")

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, 380])
        self.setCentralWidget(splitter)

        self.hud = Hud(self.view)
        self.view.resized.connect(lambda: self.hud.resize(self.view.size()))
        self.hud.set_report(self.name, sim.report(), overlay)
        self.hud.resize(self.view.size())

        self.view.groups_changed.connect(self._sync_hud)
        self.view.fps_measured.connect(self._show_fps)
        self.view.layer_changed.connect(self._show_layer)
        self.panel.commands_changed.connect(self._commands_changed)
        self.panel.situation_changed.connect(self._refresh_scene)
        self.panel.selection_changed.connect(self._select_lever)
        self.panel.sim_action.connect(self._sim_action)
        self.panel.renamed.connect(self._refresh_scene)
        self.diagnostics.anomaly_selected.connect(self._select_anomaly)
        self.curves.export_requested.connect(self._export_csv)
        self.curves.reference_requested.connect(self._load_reference)
        self.curves.replay_requested.connect(self._load_replay)
        self.curves.replay_seek.connect(self._seek_replay)
        self.curves.scenario_requested.connect(self._scenario_action)
        # Enregistre les mouvements de commande pour en faire un scenario :
        # une manoeuvre refaite a la main n'est jamais tout a fait la meme.
        self.recorder = Recorder(self.sim)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._advance)

        stats = self.mesh.stats()
        self._base = ("%d blocs · %d triangles · %s"
                      % (stats["blocs"], stats["triangles"], HELP))
        self.statusBar().showMessage(self._base)

    def set_recent(self, paths) -> None:
        """Met a jour « Ouvrir un recent »."""
        fill_recent(self, self._recent_menu, list(paths))

    # -- construction des couches ------------------------------------------
    def _overlay(self):
        forces = self.sim.current_forces()
        return build_force_overlay(
            forces, com=self.sim.mass.com,
            span=max(self.model.structure.size),
            lift_centre=lift_centre(forces),
            torque=torque_about(forces, self.sim.mass.com),
            resultant=resultant(forces))

    def _build_pocket_meshes(self):
        return [(build_cells_mesh(pocket.air, self.model.structure.size,
                                  POCKET_EMPTY),
                 "poche %d" % (index + 1))
                for index, pocket in enumerate(self.model.organ("ballons").pockets)]

    def _fills(self):
        """Taux de remplissage de chaque poche, a l'instant present."""
        out = []
        for index, pocket in enumerate(self.model.organ("ballons").pockets):
            gas = self.sim.state.gas[index] if index < len(self.sim.state.gas) else 0.0
            out.append(min(1.0, gas / max(pocket.capacity, 1)))
        return out

    def _volume_tints(self):
        return [tuple(POCKET_EMPTY[i] + (POCKET_FULL[i] - POCKET_EMPTY[i]) * fill
                      for i in range(3)) for fill in self._fills()]

    def _kinetic_mesh(self):
        return build_kinetic_mesh(
            self.model.structure, self.model, self.sim.state.speeds,
            self.model.tables.get("kinetics.max_rotation_speed"))

    # -- boucle -------------------------------------------------------------
    def _advance(self) -> None:
        if self.replay is not None:
            return          # en rejeu, la simulation ne tourne pas
        for _ in range(self.speed):
            self.sim.step()
            self.trace.record(self.sim)
        self._refresh_scene(rebuild_kinetic=False)

    def _refresh_scene(self, rebuild_kinetic: bool = True) -> None:
        overlay = self._overlay()
        self.overlay_data = overlay
        self.view.set_overlay(overlay)
        self.view.set_volume_tints(self._volume_tints())
        if rebuild_kinetic and self.view.block_layer == "cinetique":
            # Le maillage teinte par regime est couteux : on ne le refait que
            # si les regimes ont pu changer, et seulement s'il est affiche.
            self.view.set_blocks(None, self._kinetic_mesh())
        report = self.sim.report()
        self.hud.set_report(self.name, report, overlay)
        self.hud.visible_groups = set(self.view.visible_groups)
        self.panel.refresh()
        self.diagnostics.set_anomalies(report.get("anomalies") or [])
        self.curves.refresh()

    def _commands_changed(self) -> None:
        self.sim._solve(self.sim.state)
        self.recorder.capture()
        self._refresh_scene()

    def _sim_action(self, action: str) -> None:
        if action == "play":
            self.timer.start()
        elif action == "pause":
            self.timer.stop()
        elif action == "step":
            self.sim.step()
            self._refresh_scene(rebuild_kinetic=False)
        elif action == "reset":
            self.timer.stop()
            self.panel.play.setChecked(False)
            self._stop_replay()
            self.sim.reset()
            self.trace = Trace()
            self.trace.record(self.sim)
            self.curves.set_trace(self.trace)
            self.recorder = Recorder(self.sim)
            self._refresh_scene()
        elif action == "static":
            # F2.7 : converger sans regarder le transitoire
            ticks = self.sim.run_until_stable(trace=self.trace)
            self._refresh_scene()
            self.statusBar().showMessage(
                "equilibre atteint en %d ticks (%.1f s) · %s"
                % (ticks, ticks / 20.0, self._base))
        elif action.startswith("speed:"):
            self.speed = int(action.split(":")[1])

    # -- selection ----------------------------------------------------------
    def _select_lever(self, lever) -> None:
        """F4.3 : met en evidence la commande et ses destinataires."""
        mesh = build_marked_mesh(
            [([lever.pos], SELECTED_COLOR), (sorted(lever.targets), TARGET_COLOR)],
            self.model.structure.size)
        self.view.set_highlight(mesh)
        libelle = self.model.names.describe(
            "levier", lever.pos, "levier %s" % (list(lever.pos),))
        self.statusBar().showMessage(
            "%s · commande %d organe(s) · %s"
            % (libelle, len(lever.targets), self._base))

    # -- diagnostic (F5) ----------------------------------------------------
    def _select_anomaly(self, anomaly: dict) -> None:
        """Situer une anomalie : « rotor soude a la coque » ne sert a rien si
        on doit ensuite chercher OU."""
        blocks = [tuple(int(v) for v in b) for b in (anomaly.get("blocs") or [])]
        if not blocks:
            return
        self.view.set_highlight(build_marked_mesh(
            [(blocks, ANOMALY_COLOR)], self.model.structure.size))
        self.statusBar().showMessage(
            "%s · %s · %d bloc(s) · %s"
            % (anomaly.get("code", ""), anomaly.get("titre", ""),
               len(blocks), self._base))

    # -- telemetrie ---------------------------------------------------------
    def _export_csv(self) -> None:
        default = str(Path(self.model.structure.path or "trace").with_suffix(".csv"))
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter la trace", default, "CSV (*.csv)")
        if not path:
            return
        self.trace.to_csv(path)
        note = " (tronquee)" if self.trace.truncated else ""
        self.statusBar().showMessage(
            "trace exportee : %d enregistrements%s vers %s"
            % (len(self.trace), note, path))

    def _open_trace(self, title: str) -> Trace | None:
        default = str(Path(self.model.structure.path or ".").parent)
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, title, default, "CSV (*.csv)")
        if not path:
            return None
        try:
            return Trace.from_csv(path)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Trace illisible", str(exc))
            return None

    def _load_reference(self) -> None:
        trace = self._open_trace("Charger une trace de reference")
        if trace is None:
            return
        self.curves.set_reference(trace)
        self.statusBar().showMessage(
            "reference : %d enregistrements superposes · %s"
            % (len(trace), self._base))

    # -- scenarios (L4) -----------------------------------------------------
    def _scenario_action(self, action: str) -> None:
        if action == "save":
            self._save_scenario()
        elif action == "compare":
            self._compare_scenario()
        elif action == "load":
            self._load_scenario()

    def _scenario_dir(self) -> str:
        try:
            return str(default_library())
        except FileNotFoundError:
            return str(Path(self.model.structure.path or ".").parent)

    def _save_scenario(self) -> None:
        """Fige la session courante en scenario rejouable."""
        name = Path(self.model.structure.path or "vaisseau").stem
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Enregistrer ce scenario",
            str(Path(self._scenario_dir()) / ("%s.json" % name)),
            "Scenario (*.json)")
        if not path:
            return
        scenario = self.recorder.scenario(
            Path(path).stem.replace("-", " "),
            Path(self.model.structure.path or name).name)
        scenario.save(path)
        self.statusBar().showMessage(
            "scenario enregistre : %d commandes sur %d ticks · %s"
            % (len(scenario.commandes), scenario.ticks, Path(path).name))

    def _pick_scenario(self, title: str) -> Scenario | None:
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, title, self._scenario_dir(), "Scenario (*.json)")
        if not path:
            return None
        try:
            return Scenario.load(path)
        except (OSError, ValueError, KeyError) as exc:
            QtWidgets.QMessageBox.warning(self, "Scenario illisible", str(exc))
            return None

    def _compare_scenario(self) -> None:
        """Superpose l'execution d'un scenario a la trace courante.

        Le cahier tranche le multi-vaisseaux : un seul a la fois, et la
        comparaison passe par la superposition de deux executions.
        """
        scenario = self._pick_scenario("Comparer a un scenario")
        if scenario is None:
            return
        try:
            other = scenario.run(self.model.tables)
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.warning(self, "Vaisseau introuvable", str(exc))
            return
        self.curves.set_reference(other)
        result = compare(other, self.trace)
        message = "comparaison a « %s » : %s" % (scenario.nom, result.verdict)
        if result.bouges:
            first = result.bouges[0]
            message += " — %s %.2f → %.2f %s" % (first.nom, first.avant or 0.0,
                                                 first.apres or 0.0, first.unite)
        self.statusBar().showMessage(message)

    def _load_scenario(self) -> None:
        """Charge un scenario et l'execute sur le vaisseau courant."""
        scenario = self._pick_scenario("Charger un scenario")
        if scenario is None:
            return
        self.timer.stop()
        self.panel.play.setChecked(False)
        self._stop_replay()
        self.sim.options = replace(scenario.options)
        try:
            self.trace = scenario.run(self.model.tables, sim=self.sim)
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.warning(self, "Vaisseau introuvable", str(exc))
            return
        self.curves.set_trace(self.trace)
        self.recorder = Recorder(self.sim)
        self.panel.refresh()
        self._refresh_scene()
        self.statusBar().showMessage(
            "scenario « %s » joue : %d ticks, %d enregistrements"
            % (scenario.nom, scenario.ticks, len(self.trace)))

    # -- rejeu --------------------------------------------------------------
    def _load_replay(self) -> None:
        trace = self._open_trace("Rejouer une trace enregistree")
        if trace is None or not len(trace):
            return
        self.timer.stop()
        self.panel.play.setChecked(False)
        self.replay = trace
        self.curves.set_trace(trace)
        self.curves.start_replay(trace)
        self._seek_replay(0)

    def _seek_replay(self, index: int) -> None:
        """Rejoue un tick enregistre.

        Les forces sont celles du fichier ; leurs POINTS d'application viennent
        du modele, qui est le meme. Une trace se relit donc avec son vaisseau.
        """
        trace = self.replay
        if trace is None or not (0 <= index < len(trace)):
            return
        row = trace.rows[index]
        st = self.sim.state
        st.tick = int(row.get("tick", 0))
        st.position = [float(row.get("x", 0.0)), float(row.get("y", 63.0)),
                       float(row.get("z", 0.0))]
        st.velocity = [float(row.get("vx", 0.0)), float(row.get("vy", 0.0)),
                       float(row.get("vz", 0.0))]
        st.pressure = float(row.get("pression", 1.0))
        st.on_ground = bool(row.get("au_sol", 0))

        vectors = trace.vectors_at(index)
        forces = [replace(f, vector=vectors[f.key]) if f.key in vectors else f
                  for f in self.sim.current_forces(st)]
        overlay = build_force_overlay(
            forces, com=self.sim.mass.com, span=max(self.model.structure.size),
            lift_centre=lift_centre(forces),
            torque=torque_about(forces, self.sim.mass.com),
            resultant=resultant(forces))
        self.overlay_data = overlay
        self.view.set_overlay(overlay)
        self.curves.set_replay_position(index, trace)
        inconnues = [k for k in trace.force_keys
                     if k not in {f.key for f in forces}]
        self.statusBar().showMessage(
            "REJEU · tick %d · %.2f s · altitude %.2f%s · %s"
            % (st.tick, row.get("temps_s", 0.0), st.position[1],
               (" · %d force(s) du fichier sans equivalent dans ce vaisseau"
                % len(inconnues)) if inconnues else "", self._base))

    def _stop_replay(self) -> None:
        if self.replay is None:
            return
        self.replay = None
        self.curves.stop_replay()
        self.curves.set_trace(self.trace)

    # -- accessoires --------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.hud.resize(self.view.size())

    def _sync_hud(self) -> None:
        self.hud.visible_groups = set(self.view.visible_groups)
        self.hud.update()

    def _show_layer(self, layer: str) -> None:
        self.hud.mode = ("reseau cinetique, teinte par regime"
                         if layer == "cinetique" else "")
        if layer == "cinetique":
            self.view.set_blocks(None, self._kinetic_mesh())
        self.hud.update()

    def _show_fps(self, fps: float) -> None:
        if not self.timer.isActive():
            return          # au repos on ne redessine qu'a la demande
        self.statusBar().showMessage("rendu %.0f images/s · %s" % (fps, self._base))


def _load(path: str, tables=None, options: SimOptions | None = None):
    model = VehicleModel.load(path, tables)
    return model, Simulation(model, options or SimOptions())


def run(path: str | None = None, tables=None, bench_seconds: float = 0.0,
        width: int = 1280, height: int = 720) -> int:
    """Ouvre la fenetre. Avec `bench_seconds`, mesure la cadence puis sort.

    Sans `path`, l'accueil s'ouvre. Le travail est celui du lanceur : c'est lui
    qui sait ouvrir un fichier, en remplacer un autre, et ne pas planter sur un
    `.nbt` qui n'en est pas un.
    """
    from .launcher import run as launch
    return launch([path] if path else [], tables, bench_seconds, None,
                  width, height, verbose=True)
