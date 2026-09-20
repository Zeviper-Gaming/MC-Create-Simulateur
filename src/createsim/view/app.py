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

from PySide6 import QtCore, QtGui, QtWidgets

from ..model.vehicle import VehicleModel
from ..sim.forces import lift_centre, resultant, torque_about
from ..sim.state import SimOptions
from ..sim.tick import Simulation
from .cubes import CubeView, default_format
from .hud import Hud
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

TICK_MS = 50

HELP = ("souris : orbite, molette : zoom, clic droit : translation   |   "
        "1-9 filtre une force, F toutes, B le gaz, K le regime   |   "
        "A avant, C cote, H dessus, P arriere, I iso, R recadrer")


class VehicleWindow(QtWidgets.QMainWindow):
    """Vue 3D a gauche, bandeau de controle a droite, boucle au milieu."""

    def __init__(self, model: VehicleModel, sim: Simulation):
        super().__init__()
        self.model = model
        self.sim = sim
        self.speed = 1
        self.name = (model.structure.path or "").replace("\\", "/").split("/")[-1]
        self.setWindowTitle("createsim — %s" % self.name)

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
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, 360])
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

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._advance)

        stats = self.mesh.stats()
        self._base = ("%d blocs · %d triangles · %s"
                      % (stats["blocs"], stats["triangles"], HELP))
        self.statusBar().showMessage(self._base)

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
        for _ in range(self.speed):
            self.sim.step()
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
        self.hud.set_report(self.name, self.sim.report(), overlay)
        self.hud.visible_groups = set(self.view.visible_groups)
        self.panel.refresh()

    def _commands_changed(self) -> None:
        self.sim._solve(self.sim.state)
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
            self.sim.reset()
            self._refresh_scene()
        elif action == "static":
            # F2.7 : converger sans regarder le transitoire
            ticks = self.sim.run_until_stable()
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


def run(path: str, tables=None, bench_seconds: float = 0.0,
        width: int = 1280, height: int = 720) -> int:
    """Ouvre la fenetre. Avec `bench_seconds`, mesure la cadence puis sort."""
    QtGui.QSurfaceFormat.setDefaultFormat(default_format())
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])

    start = time.perf_counter()
    model, sim = _load(path, tables)
    window = VehicleWindow(model, sim)
    build_time = time.perf_counter() - start

    window.resize(width, height)
    window.show()

    stats = window.mesh.stats()
    print("maillage    : %d blocs -> %d quadrilateres (%.1f %% fusionnes), "
          "%d triangles"
          % (stats["blocs"], stats["quadrilateres"],
             stats["reduction_par_fusion"] * 100, stats["triangles"]))
    drawn = sum(e["dessinees"] for e in window.overlay_data.legend)
    print("forces      : %d vecteurs, echelle 1 bloc = %.0f"
          % (drawn, (1.0 / window.overlay_data.scale)
             if window.overlay_data.scale else 0))
    print("commandes   : %d levier(s), %d consommateur(s)"
          % (len(model.organ("redstone").levers),
             len(model.organ("redstone").consumers)))
    print("chargement  : %.2f s" % build_time)

    if not bench_seconds:
        return app.exec()

    # --- mesure : la boucle complete, simulation ET rendu ---
    frames = 0
    for _ in range(10):
        window.view.update()
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
    begin = time.perf_counter()
    deadline = begin + bench_seconds
    while time.perf_counter() < deadline:
        window._advance()
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
        frames += 1
    elapsed = time.perf_counter() - begin
    rate = frames / elapsed if elapsed else 0.0
    print("boucle      : %.0f tours/s sur %.1f s (%d tours, %dx%d)"
          % (rate, elapsed, frames, width, height))
    print("NF1 (20 ticks/s obligatoire) : %s" % ("TENU" if rate >= 20 else "NON TENU"))
    window.close()
    return 0 if rate >= 20 else 1
