"""Geometrie de l'affichage des forces : fleches, marqueurs, bras de levier.

C'est la raison d'etre du logiciel. La fenetre principale montre le vehicule ET
les forces qui s'exercent dessus ; la seconde partie est ce qu'aucun rendu joli
n'apporterait, parce qu'en jeu on voit le resultat et jamais la decomposition.

Chaque force est dessinee a SON POINT D'APPLICATION, avec une longueur
proportionnelle a son intensite (F3.6). La resultante et le couple net sont
distincts des forces elementaires (F3.8), et le bras de levier entre centre de
masse et centre de portance est materialise (F3.9).

Comme `mesh`, ce module ne connait ni Qt ni OpenGL : il produit des tableaux de
sommets et se teste sans fenetre.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

Vec = tuple[float, float, float]

# Couleurs des forces. Franches et saturees, pour se detacher des couleurs
# plates et desaturees des familles de blocs.
FORCE_COLORS = {
    "gravite": (0.95, 0.35, 0.35),
    "ballon": (0.38, 0.74, 1.00),
    "levitite": (0.72, 0.56, 1.00),
    "helice": (0.34, 0.92, 0.58),
    "roue": (1.00, 0.72, 0.26),
    "trainee": (0.96, 0.52, 0.86),
}
RESULTANT_COLOR = (1.00, 1.00, 1.00)
TORQUE_COLOR = (1.00, 0.86, 0.32)
MASS_COLOR = (1.00, 0.45, 0.40)
LIFT_COLOR = (0.42, 0.78, 1.00)
ARM_COLOR = (0.85, 0.85, 0.90)

# Groupes filtrables (F3.10)
EXTRA_GROUPS = ("resultante", "couple", "centres")

#: une force sous ce rapport a la plus grande n'est pas dessinee : sa fleche
#: ferait moins d'un pixel et salirait l'image sans rien apprendre.
NEGLIGIBLE = 0.005


@dataclass
class Overlay:
    """Geometrie de surimpression, groupee pour pouvoir filtrer l'affichage."""

    positions: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    normals: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    colors: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    legend: list[dict] = field(default_factory=list)
    scale: float = 0.0
    reference: float = 0.0

    @property
    def vertices(self) -> int:
        return self.positions.size // 3

    @property
    def groups(self) -> list[str]:
        return list(self.ranges)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def _normalise(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 1.0, 0.0])


def _basis(direction) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Repere orthonorme dont le troisieme vecteur suit `direction`."""
    w = _normalise(direction)
    helper = np.array([0.0, 0.0, 1.0]) if abs(w[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
    u = _normalise(np.cross(helper, w))
    v = np.cross(w, u)
    return u, v, w


def _ring(centre, u, v, radius, sides):
    angles = np.linspace(0.0, 2.0 * math.pi, sides, endpoint=False)
    return (np.asarray(centre)[None, :]
            + radius * (np.cos(angles)[:, None] * u[None, :]
                        + np.sin(angles)[:, None] * v[None, :]))


def _tube(a, b, radius, sides=8):
    """Prisme ferme entre deux points. Renvoie (positions, normales)."""
    u, v, _w = _basis(np.asarray(b) - np.asarray(a))
    lower = _ring(a, u, v, radius, sides)
    upper = _ring(b, u, v, radius, sides)
    pos, nor = [], []
    for i in range(sides):
        j = (i + 1) % sides
        n0 = _normalise(lower[i] - np.asarray(a))
        n1 = _normalise(lower[j] - np.asarray(a))
        pos += [lower[i], upper[i], upper[j], lower[i], upper[j], lower[j]]
        nor += [n0, n0, n1, n0, n1, n1]
    return np.array(pos, np.float32), np.array(nor, np.float32)


def _cone(base, tip, radius, sides=10):
    centre = np.asarray(base, dtype=np.float64)
    apex = np.asarray(tip, dtype=np.float64)
    u, v, w = _basis(apex - centre)
    ring = _ring(centre, u, v, radius, sides)
    pos, nor = [], []
    for i in range(sides):
        j = (i + 1) % sides
        side = _normalise(np.cross(ring[j] - ring[i], apex - ring[i]))
        pos += [ring[i], apex, ring[j]]
        nor += [side, side, side]
        # disque de fermeture
        pos += [ring[j], centre, ring[i]]
        nor += [-w, -w, -w]
    return np.array(pos, np.float32), np.array(nor, np.float32)


def arrow(origin, direction, length, radius, sides=8, head=0.32):
    """Une fleche : fut cylindrique puis pointe conique."""
    w = _normalise(direction)
    origin = np.asarray(origin, dtype=np.float64)
    head_length = max(length * head, radius * 2.2)
    head_length = min(head_length, length * 0.9)
    shaft_end = origin + w * (length - head_length)
    tip = origin + w * length
    p1, n1 = _tube(origin, shaft_end, radius, sides)
    p2, n2 = _cone(shaft_end, tip, radius * 2.1, sides + 2)
    return np.vstack([p1, p2]), np.vstack([n1, n2])


def octahedron(centre, size):
    """Marqueur compact, lisible sous tous les angles."""
    c = np.asarray(centre, dtype=np.float64)
    axes = [np.array([size, 0, 0.0]), np.array([0.0, size, 0]),
            np.array([0.0, 0, size])]
    pos, nor = [], []
    for sx in (1, -1):
        for sy in (1, -1):
            for sz in (1, -1):
                a = c + axes[0] * sx
                b = c + axes[1] * sy
                d = c + axes[2] * sz
                normal = _normalise(np.cross(b - a, d - a))
                if np.dot(normal, (a + b + d) / 3.0 - c) < 0:
                    a, b = b, a
                    normal = -normal
                pos += [a, b, d]
                nor += [normal, normal, normal]
    return np.array(pos, np.float32), np.array(nor, np.float32)


def arc_arrow(centre, axis, radius, span=math.radians(240.0), tube=0.18,
              segments=24):
    """Arc flechee autour d'un axe : la forme qui se lit comme une rotation.

    Un couple n'est pas une force ; le dessiner comme une fleche droite le
    ferait confondre avec les autres. L'arc leve l'ambiguite sans legende.
    """
    u, v, _w = _basis(axis)
    centre = np.asarray(centre, dtype=np.float64)
    angles = np.linspace(0.0, span, segments + 1)
    points = [centre + radius * (math.cos(a) * u + math.sin(a) * v)
              for a in angles]
    pos_list, nor_list = [], []
    for i in range(segments - 1):
        p, n = _tube(points[i], points[i + 1], tube, 6)
        pos_list.append(p)
        nor_list.append(n)
    tangent = points[-1] - points[-2]
    p, n = _cone(points[-2], points[-2] + tangent * 2.6, tube * 2.4, 8)
    pos_list.append(p)
    nor_list.append(n)
    return np.vstack(pos_list), np.vstack(nor_list)


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------
class _Builder:
    def __init__(self):
        self.pos: list[np.ndarray] = []
        self.nor: list[np.ndarray] = []
        self.col: list[np.ndarray] = []
        self.ranges: dict[str, tuple[int, int]] = {}
        self._count = 0
        self._group_start = 0
        self._group: str | None = None

    def open(self, name: str) -> None:
        self.close()
        self._group = name
        self._group_start = self._count

    def close(self) -> None:
        if self._group is not None and self._count > self._group_start:
            first, span = self._group_start, self._count - self._group_start
            if self._group in self.ranges:
                prev_first, prev_span = self.ranges[self._group]
                self.ranges[self._group] = (prev_first, prev_span + span)
            else:
                self.ranges[self._group] = (first, span)
        self._group = None

    def add(self, positions, normals, color) -> None:
        n = len(positions)
        if not n:
            return
        self.pos.append(positions)
        self.nor.append(normals)
        self.col.append(np.tile(np.asarray(color, np.float32), (n, 1)))
        self._count += n

    def finish(self, legend, scale, reference) -> Overlay:
        self.close()
        if not self.pos:
            return Overlay(legend=legend, scale=scale, reference=reference)
        return Overlay(
            positions=np.concatenate(self.pos).ravel().astype(np.float32),
            normals=np.concatenate(self.nor).ravel().astype(np.float32),
            colors=np.concatenate(self.col).ravel().astype(np.float32),
            ranges=self.ranges, legend=legend, scale=scale, reference=reference)


def build_force_overlay(forces, com, span, lift_centre=None, torque=None,
                        resultant=None, reference_ratio=0.38) -> Overlay:
    """Assemble la surimpression complete.

    `span` est la plus grande dimension du vehicule : elle fixe l'echelle, pour
    qu'un vaisseau de 20 blocs et un de 200 se lisent pareil. La plus grande
    force occupe `reference_ratio` de cette dimension, et toutes les autres
    suivent proportionnellement — c'est l'exigence F3.6, et c'est ce qui permet
    de comparer deux fleches a l'oeil.
    """
    builder = _Builder()
    legend: list[dict] = []
    span = max(float(span), 1.0)
    reference = span * reference_ratio

    magnitudes = [f.magnitude for f in forces]
    if resultant is not None:
        magnitudes.append(float(np.linalg.norm(resultant)))
    peak = max(magnitudes) if magnitudes else 0.0
    scale = reference / peak if peak > 0 else 0.0
    thickness = max(span * 0.012, 0.16)

    # --- forces elementaires, groupees par famille ------------------------
    by_family: dict[str, list] = {}
    for force in forces:
        by_family.setdefault(force.family, []).append(force)

    for family, group in by_family.items():
        color = FORCE_COLORS.get(family, (0.8, 0.8, 0.8))
        total = sum(f.magnitude for f in group)
        drawn = 0
        builder.open(family)
        for force in group:
            if peak <= 0 or force.magnitude <= peak * NEGLIGIBLE:
                continue
            length = force.magnitude * scale
            p, n = arrow(force.point, force.vector, length, thickness)
            builder.add(p, n, color)
            drawn += 1
        builder.close()
        legend.append({
            "groupe": family, "couleur": color, "intensite": total,
            "nombre": len(group), "dessinees": drawn,
            "negligeable": len(group) - drawn,
        })

    # --- resultante et couple, distincts des forces elementaires ----------
    if resultant is not None:
        magnitude = float(np.linalg.norm(resultant))
        if magnitude > 0 and peak > 0:
            builder.open("resultante")
            p, n = arrow(com, resultant, magnitude * scale, thickness * 1.5)
            builder.add(p, n, RESULTANT_COLOR)
            builder.close()
        legend.append({"groupe": "resultante", "couleur": RESULTANT_COLOR,
                       "intensite": magnitude, "nombre": 1,
                       "dessinees": 1 if magnitude > 0 else 0, "negligeable": 0})

    if torque is not None:
        magnitude = float(np.linalg.norm(torque))
        if magnitude > 1e-9:
            builder.open("couple")
            p, n = arc_arrow(com, torque, span * 0.16, tube=thickness * 0.9)
            builder.add(p, n, TORQUE_COLOR)
            builder.close()
        legend.append({"groupe": "couple", "couleur": TORQUE_COLOR,
                       "intensite": magnitude, "nombre": 1,
                       "dessinees": 1 if magnitude > 1e-9 else 0,
                       "negligeable": 0, "unite": "N.bloc"})

    # --- centres et bras de levier (F3.9) ---------------------------------
    marker = max(span * 0.018, 0.30)
    builder.open("centres")
    p, n = octahedron(com, marker)
    builder.add(p, n, MASS_COLOR)
    arm = None
    if lift_centre is not None:
        p, n = octahedron(lift_centre, marker)
        builder.add(p, n, LIFT_COLOR)
        offset = np.asarray(lift_centre) - np.asarray(com)
        # Seule la composante HORIZONTALE produit un moment sous une force
        # verticale : c'est elle le bras de levier qui fait piquer du nez.
        # L'ecart vertical, lui, ne bascule rien.
        arm_horizontal = float(math.hypot(offset[0], offset[2]))
        distance = float(np.linalg.norm(offset))
        if distance > 1e-6:
            p, n = _tube(com, lift_centre, thickness * 0.45, 6)
            builder.add(p, n, ARM_COLOR)
            arm = arm_horizontal
    builder.close()
    legend.append({"groupe": "centres", "couleur": LIFT_COLOR,
                   "intensite": arm or 0.0, "nombre": 2,
                   "dessinees": 2, "negligeable": 0,
                   "unite": "blocs de bras horizontal"})

    return builder.finish(legend, scale, reference)
