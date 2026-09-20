"""Fenetre de L1 : le vehicule et les forces qui s'exercent dessus.

Lecture seule. Elle ne pilote rien et ne fait pas tourner la simulation : elle
montre l'etat initial, ce qui suffit deja a repondre a « pourquoi ca pique du
nez ? » — voir le vecteur de portance applique en avant ou en arriere du centre
de masse, et le couple qui en resulte.
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
from .mesh import (build_cells_mesh, build_kinetic_mesh, build_mesh,
                   families_from_model)
from .vectors import build_force_overlay

#: teinte des poches de gaz, du vide au plein (F3.11)
POCKET_EMPTY = (0.42, 0.46, 0.55)
POCKET_FULL = (0.40, 0.78, 1.00)

HELP = ("souris : orbite, molette : zoom, clic droit : translation   |   "
        "1-9 filtre une force, F toutes, B le gaz, K le regime   |   "
        "A avant, C cote, H dessus, P arriere, I iso, R recadrer")


class VehicleWindow(QtWidgets.QMainWindow):
    """La fenetre principale : une vue 3D, et rien qui la masque."""

    def __init__(self, model: VehicleModel, sim: Simulation):
        super().__init__()
        self.model = model
        self.sim = sim
        name = (model.structure.path or "").replace("\\", "/").split("/")[-1]
        self.setWindowTitle("createsim — %s" % name)

        mesh = build_mesh(model.structure, families_from_model(model))
        forces = sim.current_forces()
        overlay = build_force_overlay(
            forces,
            com=sim.mass.com,
            span=max(model.structure.size),
            lift_centre=lift_centre(forces),
            torque=torque_about(forces, sim.mass.com),
            resultant=resultant(forces),
        )
        volumes = _pocket_volumes(model, sim)
        kinetic = build_kinetic_mesh(model.structure, model, sim.state.speeds,
                                     model.tables.get("kinetics.max_rotation_speed"))

        self.view = CubeView(mesh, overlay, volumes, kinetic)
        self.setCentralWidget(self.view)
        self.hud = Hud(self.view)
        self.hud.set_report(name, sim.report(), overlay)
        self.hud.resize(self.view.size())
        self.view.groups_changed.connect(self._sync_hud)
        self.view.fps_measured.connect(self._show_fps)
        self.view.layer_changed.connect(self._show_layer)

        stats = mesh.stats()
        self._base = ("%d blocs · %d triangles · %d force(s) · %s"
                      % (stats["blocs"], stats["triangles"], len(forces), HELP))
        self.statusBar().showMessage(self._base)
        self.overlay_data = overlay
        self.mesh = mesh

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.hud.resize(self.view.size())

    def _sync_hud(self) -> None:
        self.hud.visible_groups = set(self.view.visible_groups)
        self.hud.update()

    def _show_layer(self, layer: str) -> None:
        self.hud.mode = ("reseau cinetique, teinte par regime"
                         if layer == "cinetique" else "")
        self.hud.update()

    def _show_fps(self, fps: float) -> None:
        self.statusBar().showMessage("%.0f images/s · %s" % (fps, self._base))


def _pocket_volumes(model: VehicleModel, sim: Simulation):
    """Volume de gaz de chaque poche, teinte par son taux de remplissage."""
    pockets = model.organ("ballons").pockets
    out = []
    for index, pocket in enumerate(pockets):
        capacity = max(pocket.capacity, 1)
        fill = min(1.0, (sim.state.gas[index] if index < len(sim.state.gas)
                         else 0.0) / capacity)
        color = tuple(POCKET_EMPTY[i] + (POCKET_FULL[i] - POCKET_EMPTY[i]) * fill
                      for i in range(3))
        mesh = build_cells_mesh(pocket.air, model.structure.size, color)
        out.append((mesh, "poche %d : %.0f %%" % (index + 1, fill * 100)))
    return out


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
    print("maillage    : %d blocs -> %d faces visibles -> %d quadrilateres "
          "(%.1f %% fusionnes)"
          % (stats["blocs"], stats["faces_visibles"], stats["quadrilateres"],
             stats["reduction_par_fusion"] * 100))
    print("             %d triangles, %.2f Mo sur le GPU"
          % (stats["triangles"], stats["octets_gpu"] / 1048576))
    drawn = sum(e["dessinees"] for e in window.overlay_data.legend)
    print("forces      : %d vecteurs dessines, echelle 1 bloc = %.0f"
          % (drawn,
             (1.0 / window.overlay_data.scale) if window.overlay_data.scale else 0))
    print("chargement  : %.2f s (modele, simulation, maillage, vecteurs)"
          % build_time)

    if not bench_seconds:
        return app.exec()

    frames = 0
    for _ in range(10):
        window.view.update()
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
    begin = time.perf_counter()
    deadline = begin + bench_seconds
    while time.perf_counter() < deadline:
        window.view.update()
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
        frames += 1
    elapsed = time.perf_counter() - begin
    fps = frames / elapsed if elapsed else 0.0
    print("cadence     : %.0f images/s sur %.1f s (%d images, %dx%d)"
          % (fps, elapsed, frames, width, height))
    print("NF2 (60 images/s souhaite) : %s" % ("TENU" if fps >= 60 else "NON TENU"))
    window.close()
    return 0 if fps >= 60 else 1
