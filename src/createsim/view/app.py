"""Fenetre minimale du spike 3D, et sa mesure de cadence.

Le cahier borne le risque de la 3D a un module autonome, « testable avant que le
reste de l'interface existe ». C'est exactement ce que cette fenetre fait : elle
n'affiche que les blocs, sans bandeau, sans forces, sans boucle de simulation.
"""
from __future__ import annotations

import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets

from ..model.vehicle import VehicleModel
from .cubes import CubeView, default_format
from .mesh import COLORS, FAMILIES, build_mesh, families_from_model


class SpikeWindow(QtWidgets.QMainWindow):
    def __init__(self, model: VehicleModel, mesh):
        super().__init__()
        name = (model.structure.path or "").replace("\\", "/").split("/")[-1]
        self.setWindowTitle("createsim — %s" % name)
        self.view = CubeView(mesh)
        self.setCentralWidget(self.view)

        legend = " · ".join(
            "%s" % family for family in FAMILIES)
        stats = mesh.stats()
        self.status = self.statusBar()
        self.status.showMessage(
            "%d blocs · %d quadrilateres (%.0f %% de faces fusionnees) · "
            "%d triangles · %.1f Mo GPU · %s"
            % (stats["blocs"], stats["quadrilateres"],
               stats["reduction_par_fusion"] * 100, stats["triangles"],
               stats["octets_gpu"] / 1048576, legend))
        self.view.fps_measured.connect(self._show_fps)
        self._base = self.status.currentMessage()

    def _show_fps(self, fps: float) -> None:
        self.status.showMessage("%.0f images/s · %s" % (fps, self._base))


def _load(path: str, tables=None):
    model = VehicleModel.load(path, tables)
    mesh = build_mesh(model.structure, families_from_model(model))
    return model, mesh


def run(path: str, tables=None, bench_seconds: float = 0.0,
        width: int = 1280, height: int = 720) -> int:
    """Ouvre la fenetre. Avec `bench_seconds`, mesure la cadence puis sort."""
    QtGui.QSurfaceFormat.setDefaultFormat(default_format())
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])

    build_start = time.perf_counter()
    model, mesh = _load(path, tables)
    build_time = time.perf_counter() - build_start

    window = SpikeWindow(model, mesh)
    window.resize(width, height)
    window.show()

    stats = mesh.stats()
    print("maillage    : %d blocs -> %d faces visibles -> %d quadrilateres "
          "(%.1f %% fusionnes)"
          % (stats["blocs"], stats["faces_visibles"], stats["quadrilateres"],
             stats["reduction_par_fusion"] * 100))
    print("             %d triangles, %.2f Mo sur le GPU, construit en %.2f s"
          % (stats["triangles"], stats["octets_gpu"] / 1048576, build_time))

    if not bench_seconds:
        return app.exec()

    # --- mesure : on force le rendu aussi vite que la machine le permet ---
    frames = 0
    deadline = time.perf_counter() + bench_seconds
    warmup = 10
    for _ in range(warmup):
        window.view.update()
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
    start = time.perf_counter()
    while time.perf_counter() < deadline:
        window.view.update()
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
        frames += 1
    elapsed = time.perf_counter() - start
    fps = frames / elapsed if elapsed else 0.0
    print("cadence     : %.0f images/s sur %.1f s (%d images, %dx%d)"
          % (fps, elapsed, frames, width, height))
    print("NF2 (60 images/s souhaite) : %s" % ("TENU" if fps >= 60 else "NON TENU"))
    window.close()
    return 0 if fps >= 60 else 1
