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


class CubeView(QOpenGLWidget):
    """Affiche un maillage deja construit. Ne calcule aucune physique."""

    fps_measured = QtCore.Signal(float)

    def __init__(self, mesh: Mesh, parent=None, background=(0.09, 0.10, 0.12)):
        super().__init__(parent)
        self.mesh = mesh
        self.background = background
        self.camera = OrbitCamera(mesh.centre, mesh.radius,
                                  mesh.positions.reshape(-1, 3))
        self._fitted = False
        self.program: QtOpenGL.QOpenGLShaderProgram | None = None
        self.vao: QtOpenGL.QOpenGLVertexArrayObject | None = None
        self.buffers: list[QtOpenGL.QOpenGLBuffer] = []
        self.uniforms: dict[str, int] = {}
        self._last_pos = None
        self._frames = 0
        self._t0 = time.perf_counter()
        self.fps = 0.0
        self.setMinimumSize(320, 240)

    # -- cycle OpenGL ------------------------------------------------------
    def initializeGL(self) -> None:
        gl = QtGui.QOpenGLContext.currentContext().functions()
        gl.glClearColor(*self.background, 1.0)
        gl.glEnable(0x0B71)          # GL_DEPTH_TEST
        gl.glEnable(0x0B44)          # GL_CULL_FACE

        self.program = QtOpenGL.QOpenGLShaderProgram()
        self.program.addShaderFromSourceCode(
            QtOpenGL.QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SHADER)
        self.program.addShaderFromSourceCode(
            QtOpenGL.QOpenGLShader.ShaderTypeBit.Fragment, FRAGMENT_SHADER)
        if not self.program.link():
            raise RuntimeError("shader non lie : " + self.program.log())
        # PySide6 n'expose `setUniformValue` que par emplacement entier :
        # on resout les noms une fois pour toutes, apres l'edition de liens.
        self.program.bind()
        self.uniforms = {name: self.program.uniformLocation(name)
                         for name in ("mvp",)}
        self.program.release()

        self.vao = QtOpenGL.QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        for index, data in enumerate((self.mesh.positions, self.mesh.normals,
                                      self.mesh.colors)):
            buffer = QtOpenGL.QOpenGLBuffer(QtOpenGL.QOpenGLBuffer.Type.VertexBuffer)
            buffer.create()
            buffer.bind()
            buffer.setUsagePattern(QtOpenGL.QOpenGLBuffer.UsagePattern.StaticDraw)
            buffer.allocate(data.tobytes(), int(data.nbytes))
            self.program.enableAttributeArray(index)
            self.program.setAttributeBuffer(index, 0x1406, 0, 3)   # GL_FLOAT
            self.buffers.append(buffer)
        self.vao.release()

    def resizeGL(self, w: int, h: int) -> None:
        QtGui.QOpenGLContext.currentContext().functions().glViewport(0, 0, w, h)
        if not self._fitted and w > 1 and h > 1:
            self.camera.auto_orient(w / h)
            self._fitted = True

    def paintGL(self) -> None:
        gl = QtGui.QOpenGLContext.currentContext().functions()
        gl.glClear(0x00004000 | 0x00000100)   # COLOR_BUFFER_BIT | DEPTH_BUFFER_BIT
        if self.program is None or not self.mesh.vertices:
            return
        self.program.bind()
        self.vao.bind()
        aspect = self.width() / max(1, self.height())
        self.program.setUniformValue(self.uniforms["mvp"],
                                     self.camera.matrix(aspect))
        gl.glDrawArrays(0x0004, 0, self.mesh.vertices)   # GL_TRIANGLES
        self.vao.release()
        self.program.release()
        self._tick_fps()

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
        views = {QtCore.Qt.Key.Key_1: "avant", QtCore.Qt.Key.Key_2: "cote",
                 QtCore.Qt.Key.Key_3: "dessus", QtCore.Qt.Key.Key_4: "arriere",
                 QtCore.Qt.Key.Key_0: "isometrique"}
        name = views.get(event.key())
        if name:
            self.camera.look(name)
            self.camera.fit(self.width() / max(1, self.height()))
            self.update()
        else:
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
