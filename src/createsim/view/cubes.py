"""Widget OpenGL de cubes a faces fusionnees, et sa camera en orbite.

C'est le risque assume du cahier : ecrire la 3D soi-meme. Il est borne a ce
module, testable avant que le reste de l'interface existe. Le rendu est
volontairement pauvre — couleur plate par famille, un eclairage directionnel
fixe, ni ombres portees, ni occlusion ambiante, ni post-traitement.

Tout le maillage est envoye en UN SEUL tampon et dessine en UN SEUL appel. Sur
un vaisseau de 20 659 blocs cela represente une vingtaine de milliers de
triangles, soit moins d'un dixieme de ce que couterait un cube par bloc.
"""
from __future__ import annotations

import math
import time

import numpy as np

from PySide6 import QtCore, QtGui, QtOpenGL
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .mesh import Mesh

VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec3 in_normal;
layout(location = 2) in vec3 in_color;
uniform mat4 mvp;
out vec3 v_normal;
out vec3 v_color;
out vec3 v_world;
void main() {
    v_normal = in_normal;
    v_color = in_color;
    v_world = in_position;
    gl_Position = mvp * vec4(in_position, 1.0);
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec3 v_normal;
in vec3 v_color;
in vec3 v_world;
out vec4 frag_color;

// Eclairage directionnel fixe, et rien de plus : ni ombres portees, ni
// occlusion ambiante, ni post-traitement. Les constantes sont figees ici
// plutot que passees en uniforme — PySide6 n'expose `setUniformValue` que par
// emplacement entier, et un flottant y est happe par la surcharge `int`, ce
// qui annulait silencieusement l'ambiante.
const vec3  LIGHT   = normalize(vec3(0.42, 0.80, 0.43));
const float AMBIENT = 0.55;

// Grille par bloc, restituee ici plutot qu'en geometrie. La fusion gloutonne
// efface les aretes : sans elles, une coque de trente blocs n'est plus qu'un
// aplat, et on perd l'echelle. Le trait s'attenue quand un bloc couvre moins
// de deux pixels, sinon la grille moire au loin.
const float EDGE = 0.34;

void main() {
    float lambert = max(dot(normalize(v_normal), LIGHT), 0.0);
    float shade = AMBIENT + (1.0 - AMBIENT) * lambert;

    vec3 axis = abs(normalize(v_normal));
    vec2 uv = axis.x > 0.5 ? v_world.yz
            : (axis.y > 0.5 ? v_world.xz : v_world.xy);
    vec2 width = fwidth(uv);
    vec2 dist = abs(fract(uv) - 0.5) / max(width, vec2(1e-5));
    float edge = 1.0 - smoothstep(0.30, 0.95, min(dist.x, dist.y));
    edge *= 1.0 - smoothstep(0.30, 0.90, max(width.x, width.y));

    frag_color = vec4(v_color * shade * (1.0 - EDGE * edge), 1.0);
}
"""


# Le meme eclairage, sans la grille des blocs : une fleche n'est pas un volume
# de blocs, et un quadrillage dessus la rendrait illisible. L'opacite est une
# constante du shader plutot qu'un uniforme, pour la meme raison que l'ambiante.
OVERLAY_FRAGMENT = """
#version 330 core
in vec3 v_normal;
in vec3 v_color;
in vec3 v_world;
out vec4 frag_color;
const vec3  LIGHT   = normalize(vec3(0.42, 0.80, 0.43));
const float AMBIENT = 0.62;
const float ALPHA   = %.2f;
void main() {
    float lambert = max(dot(normalize(v_normal), LIGHT), 0.0);
    frag_color = vec4(v_color * (AMBIENT + (1.0 - AMBIENT) * lambert), ALPHA);
}
"""


class OrbitCamera:
    """Orbite, panoramique, zoom, et les vues normalisees du cahier (F3.2)."""

    FOV = 40.0
    MARGIN = 1.08

    def __init__(self, centre=(0.0, 0.0, 0.0), radius: float = 32.0,
                 points=None):
        self.target = list(centre)
        self.distance = radius * 3.0
        self.yaw = math.radians(35.0)
        self.pitch = math.radians(25.0)
        self.home_distance = self.distance
        self.points = points

    def fit(self, aspect: float = 16 / 9) -> None:
        """Cadre le vehicule pour l'orientation courante.

        L'ajustement porte sur les SOMMETS du maillage, pas sur la boite
        englobante : une coque longue et fine ne remplit pas sa boite, et la
        cadrer laisserait le c1_air_cruiser au tiers de l'image.
        """
        points = self.points
        if points is None or len(points) == 0:
            return
        right, up, forward = self._basis()
        half_fov = math.radians(self.FOV) / 2.0
        tan_v = math.tan(half_fov)
        tan_h = tan_v * max(aspect, 1e-3)

        rel = points - np.asarray(self.target, dtype=np.float32)
        # profondeur comptee vers la camera : `forward` pointe vers elle
        depth = -(rel @ np.asarray(forward, dtype=np.float32))
        u = np.abs(rel @ np.asarray(right, dtype=np.float32))
        v = np.abs(rel @ np.asarray(up, dtype=np.float32))
        needed = np.maximum(u / tan_h, v / tan_v) - depth
        self.distance = max(1.0, float(needed.max()) * self.MARGIN)
        self.home_distance = self.distance

    def auto_orient(self, aspect: float = 16 / 9) -> None:
        """Choisit l'orientation de depart qui remplit le mieux l'image.

        Un angle fixe cadre mal : une coque de 176 blocs de long posee en
        diagonale ne remplit que la moitie de la largeur, le reste etant du
        vide dans les coins. On essaie donc quelques azimuts et on garde celui
        qui demande le moins de recul.

        Les azimuts a moins de douze degres d'une vue de face ou de profil sont
        ecartes : ils cadrent au plus serre, mais une vue plate ne montre plus
        le relief, et c'est le relief qui situe les organes.
        """
        if self.points is None or len(self.points) == 0:
            return
        best = None
        for degrees in range(0, 360, 5):
            if min(degrees % 90, 90 - degrees % 90) < 12:
                continue
            self.yaw = math.radians(degrees)
            self.fit(aspect)
            if best is None or self.distance < best[0]:
                best = (self.distance, self.yaw)
        if best is not None:
            self.yaw = best[1]
            self.fit(aspect)

    def orbit(self, dyaw: float, dpitch: float) -> None:
        self.yaw += dyaw
        limit = math.radians(89.0)
        self.pitch = max(-limit, min(limit, self.pitch + dpitch))

    def zoom(self, factor: float) -> None:
        self.distance = max(1.0, min(self.home_distance * 8.0,
                                     self.distance * factor))

    def pan(self, dx: float, dy: float) -> None:
        right, up, _ = self._basis()
        scale = self.distance * 0.0015
        for i in range(3):
            self.target[i] -= (right[i] * dx - up[i] * dy) * scale

    def look(self, name: str) -> None:
        angles = {"dessus": (0.0, 89.0), "dessous": (0.0, -89.0),
                  "avant": (0.0, 0.0), "arriere": (180.0, 0.0),
                  "cote": (90.0, 0.0), "isometrique": (35.0, 25.0)}
        yaw, pitch = angles.get(name, angles["isometrique"])
        self.yaw, self.pitch = math.radians(yaw), math.radians(pitch)

    def _basis(self):
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        forward = (cp * sy, sp, cp * cy)
        right = (cy, 0.0, -sy)
        up = (-sp * sy, cp, -sp * cy)
        return right, up, forward

    def eye(self):
        _, _, forward = self._basis()
        return [self.target[i] + forward[i] * self.distance for i in range(3)]

    def matrix(self, aspect: float, far_scale: float = 40.0) -> QtGui.QMatrix4x4:
        projection = QtGui.QMatrix4x4()
        projection.perspective(self.FOV, aspect if aspect > 0 else 1.0,
                               max(0.05, self.distance * 0.002),
                               self.home_distance * far_scale)
        view = QtGui.QMatrix4x4()
        eye = self.eye()
        view.lookAt(QtGui.QVector3D(*eye), QtGui.QVector3D(*self.target),
                    QtGui.QVector3D(0.0, 1.0, 0.0))
        return projection * view


# Constantes OpenGL utilisees, nommees pour que le code reste lisible sans
# avoir PyOpenGL en dependance.
GL_DEPTH_TEST = 0x0B71
GL_CULL_FACE = 0x0B44
GL_BLEND = 0x0BE2
GL_TRIANGLES = 0x0004
GL_FLOAT = 0x1406
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_COLOR_BUFFER_BIT = 0x4000
GL_DEPTH_BUFFER_BIT = 0x0100


class _Batch:
    """Un jeu de sommets sur le GPU : position, normale, couleur."""

    def __init__(self, positions, normals, colors):
        self.count = positions.size // 3
        self._data = (positions, normals, colors)
        self.vao: QtOpenGL.QOpenGLVertexArrayObject | None = None
        self.buffers: list[QtOpenGL.QOpenGLBuffer] = []

    def upload(self, program) -> None:
        if not self.count:
            return
        self.vao = QtOpenGL.QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        for index, data in enumerate(self._data):
            buffer = QtOpenGL.QOpenGLBuffer(QtOpenGL.QOpenGLBuffer.Type.VertexBuffer)
            buffer.create()
            buffer.bind()
            buffer.setUsagePattern(QtOpenGL.QOpenGLBuffer.UsagePattern.StaticDraw)
            buffer.allocate(data.tobytes(), int(data.nbytes))
            program.enableAttributeArray(index)
            program.setAttributeBuffer(index, GL_FLOAT, 0, 3)
            self.buffers.append(buffer)
        self.vao.release()
        self._data = ()

    def draw(self, gl, first: int = 0, count: int | None = None) -> None:
        if not self.count or self.vao is None:
            return
        self.vao.bind()
        gl.glDrawArrays(GL_TRIANGLES, first, self.count if count is None else count)
        self.vao.release()


class CubeView(QOpenGLWidget):
    """Affiche un maillage deja construit. Ne calcule aucune physique."""

    fps_measured = QtCore.Signal(float)
    groups_changed = QtCore.Signal()
    layer_changed = QtCore.Signal(str)

    def __init__(self, mesh: Mesh, overlay=None, volumes=None, kinetic=None,
                 parent=None, background=(0.09, 0.10, 0.12)):
        super().__init__(parent)
        self.mesh = mesh
        self.kinetic = kinetic
        self.block_layer = "blocs"
        self.overlay = overlay
        self.volumes = list(volumes or [])
        self.background = background
        # Le cadrage englobe AUSSI les fleches : une force qui sort du cadre
        # ne se compare a rien, et c'est justement la comparaison qui repond
        # aux questions du cahier.
        framed = [mesh.positions.reshape(-1, 3)]
        if overlay is not None and overlay.vertices:
            framed.append(overlay.positions.reshape(-1, 3))
        self.camera = OrbitCamera(mesh.centre, mesh.radius,
                                  np.concatenate(framed))
        self._fitted = False
        self.visible_groups: set[str] = set(
            overlay.ranges if overlay is not None else ())
        self.show_volumes = True
        self.programs: dict[str, QtOpenGL.QOpenGLShaderProgram] = {}
        self.uniforms: dict[str, dict[str, int]] = {}
        self.batches: dict[str, _Batch] = {}
        self._last_pos = None
        self._frames = 0
        self._t0 = time.perf_counter()
        self.fps = 0.0
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    # -- cycle OpenGL ------------------------------------------------------
    def initializeGL(self) -> None:
        gl = QtGui.QOpenGLContext.currentContext().functions()
        gl.glClearColor(*self.background, 1.0)
        gl.glEnable(GL_DEPTH_TEST)
        gl.glEnable(GL_CULL_FACE)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        self._make_program("blocs", FRAGMENT_SHADER)
        self._make_program("surimpression", OVERLAY_FRAGMENT % 1.0)
        self._make_program("fantome", OVERLAY_FRAGMENT % 0.30)
        self._make_program("volume", OVERLAY_FRAGMENT % 0.26)

        self.batches["blocs"] = _Batch(self.mesh.positions, self.mesh.normals,
                                       self.mesh.colors)
        self.batches["blocs"].upload(self.programs["blocs"])
        if self.kinetic is not None and self.kinetic.vertices:
            batch = _Batch(self.kinetic.positions, self.kinetic.normals,
                           self.kinetic.colors)
            batch.upload(self.programs["blocs"])
            self.batches["cinetique"] = batch
        if self.overlay is not None and self.overlay.vertices:
            batch = _Batch(self.overlay.positions, self.overlay.normals,
                           self.overlay.colors)
            batch.upload(self.programs["surimpression"])
            self.batches["surimpression"] = batch
        for index, (volume, _label) in enumerate(self.volumes):
            if not volume.vertices:
                continue
            batch = _Batch(volume.positions, volume.normals, volume.colors)
            batch.upload(self.programs["volume"])
            self.batches["volume%d" % index] = batch

    def _make_program(self, name: str, fragment: str) -> None:
        program = QtOpenGL.QOpenGLShaderProgram()
        program.addShaderFromSourceCode(
            QtOpenGL.QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SHADER)
        program.addShaderFromSourceCode(
            QtOpenGL.QOpenGLShader.ShaderTypeBit.Fragment, fragment)
        if not program.link():
            raise RuntimeError("shader %s non lie : %s" % (name, program.log()))
        # PySide6 n'expose `setUniformValue` que par emplacement entier : on
        # resout les noms une fois pour toutes, apres l'edition de liens.
        program.bind()
        self.uniforms[name] = {"mvp": program.uniformLocation("mvp")}
        program.release()
        self.programs[name] = program

    def resizeGL(self, w: int, h: int) -> None:
        QtGui.QOpenGLContext.currentContext().functions().glViewport(0, 0, w, h)
        if not self._fitted and w > 1 and h > 1:
            self.camera.auto_orient(w / h)
            self._fitted = True

    def paintGL(self) -> None:
        gl = QtGui.QOpenGLContext.currentContext().functions()
        gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if not self.programs:
            return
        matrix = self.camera.matrix(self.width() / max(1, self.height()))

        # 1. les blocs, opaques
        gl.glEnable(GL_DEPTH_TEST)
        gl.glEnable(GL_CULL_FACE)
        gl.glDisable(GL_BLEND)
        self._draw(self.block_layer, "blocs", gl, matrix)

        # 2. les volumes de gaz, transparents : on les lit a travers, donc ni
        #    ecriture de profondeur ni elimination des faces arriere.
        if self.show_volumes:
            # Le gaz occupe les cellules VIDES a l'interieur de l'enveloppe :
            # teste en profondeur, il serait integralement cache par elle. On
            # le dessine donc en transparence par-dessus, comme une radio.
            gl.glEnable(GL_BLEND)
            gl.glDisable(GL_CULL_FACE)
            gl.glDisable(GL_DEPTH_TEST)
            gl.glDepthMask(False)
            for index in range(len(self.volumes)):
                self._draw("volume%d" % index, "volume", gl, matrix)
            gl.glEnable(GL_DEPTH_TEST)
            gl.glDepthMask(True)

        # 3. les forces. Deux passes : une fantome sans test de profondeur, qui
        #    montre ce que la coque cache, puis une pleine par-dessus. Sans la
        #    premiere, un centre de masse a l'interieur du vaisseau serait
        #    invisible ; sans la seconde, on perdrait toute notion de profondeur.
        if "surimpression" in self.batches:
            gl.glEnable(GL_BLEND)
            gl.glDisable(GL_CULL_FACE)
            gl.glDisable(GL_DEPTH_TEST)
            gl.glDepthMask(False)
            self._draw_overlay("fantome", gl, matrix)
            gl.glEnable(GL_DEPTH_TEST)
            gl.glDepthMask(True)
            gl.glDisable(GL_BLEND)
            self._draw_overlay("surimpression", gl, matrix)
            gl.glEnable(GL_CULL_FACE)
        self._tick_fps()

    def _draw(self, batch_name: str, program_name: str, gl, matrix) -> None:
        batch = self.batches.get(batch_name)
        if batch is None:
            return
        program = self.programs[program_name]
        program.bind()
        program.setUniformValue(self.uniforms[program_name]["mvp"], matrix)
        batch.draw(gl)
        program.release()

    def _draw_overlay(self, program_name: str, gl, matrix) -> None:
        """Ne dessine que les groupes de forces retenus par le filtre (F3.10)."""
        batch = self.batches["surimpression"]
        program = self.programs[program_name]
        program.bind()
        program.setUniformValue(self.uniforms[program_name]["mvp"], matrix)
        for group, (first, count) in self.overlay.ranges.items():
            if group in self.visible_groups:
                batch.draw(gl, first, count)
        program.release()

    def toggle_group(self, group: str) -> None:
        if group in self.visible_groups:
            self.visible_groups.discard(group)
        else:
            self.visible_groups.add(group)
        self.update()

    def _tick_fps(self) -> None:
        self._frames += 1
        elapsed = time.perf_counter() - self._t0
        if elapsed >= 0.5:
            self.fps = self._frames / elapsed
            self._frames = 0
            self._t0 = time.perf_counter()
            self.fps_measured.emit(self.fps)

    # -- interaction -------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        self._last_pos = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self._last_pos is None:
            return
        delta = event.position() - self._last_pos
        self._last_pos = event.position()
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self.camera.orbit(-delta.x() * 0.01, -delta.y() * 0.01)
        elif event.buttons() & (QtCore.Qt.MouseButton.MiddleButton
                                | QtCore.Qt.MouseButton.RightButton):
            self.camera.pan(delta.x(), delta.y())
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._last_pos = None

    def wheelEvent(self, event) -> None:
        self.camera.zoom(0.9 if event.angleDelta().y() > 0 else 1.0 / 0.9)
        self.update()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        views = {QtCore.Qt.Key.Key_A: "avant", QtCore.Qt.Key.Key_C: "cote",
                 QtCore.Qt.Key.Key_H: "dessus", QtCore.Qt.Key.Key_P: "arriere",
                 QtCore.Qt.Key.Key_I: "isometrique"}
        if key in views:
            self.camera.look(views[key])
            self.camera.fit(self.width() / max(1, self.height()))
            self.update()
            return
        if key == QtCore.Qt.Key.Key_R:
            self.camera.auto_orient(self.width() / max(1, self.height()))
            self.update()
            return
        if key == QtCore.Qt.Key.Key_K and "cinetique" in self.batches:
            self.block_layer = ("cinetique" if self.block_layer == "blocs"
                                else "blocs")
            self.layer_changed.emit(self.block_layer)
            self.update()
            return
        if key == QtCore.Qt.Key.Key_B:
            self.show_volumes = not self.show_volumes
            self.update()
            return
        if key == QtCore.Qt.Key.Key_F and self.overlay is not None:
            everything = set(self.overlay.ranges)
            self.visible_groups = set() if self.visible_groups else everything
            self.groups_changed.emit()
            self.update()
            return
        if self.overlay is not None and QtCore.Qt.Key.Key_1 <= key <= QtCore.Qt.Key.Key_9:
            index = key - QtCore.Qt.Key.Key_1
            groups = list(self.overlay.legend)
            if index < len(groups):
                self.toggle_group(groups[index]["groupe"])
                self.groups_changed.emit()
            return
        super().keyPressEvent(event)


def default_format() -> QtGui.QSurfaceFormat:
    """Contexte OpenGL 3.3 core, profondeur 24 bits, sans synchro verticale.

    La synchro verticale est coupee pour que la mesure de cadence reflete le
    cout reel du rendu et non le rafraichissement de l'ecran.
    """
    fmt = QtGui.QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSwapInterval(0)
    return fmt
