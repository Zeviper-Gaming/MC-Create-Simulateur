"""Selectionner un bloc au clic dans la vue 3D (F6.1).

Deux fonctions pures, testables sans fenetre :

    ray_from_pixel   le rayon qui part de l'oeil et passe par le pixel clique
    pick             le premier bloc plein qu'il traverse, et la face touchee

Le parcours est celui d'Amanatides et Woo : on avance de case en case le long
du rayon, en franchissant toujours la frontiere la plus proche. Aucune case
n'est sautee et aucune n'est visitee deux fois — c'est ce qui garantit qu'un
clic sur le bord d'un bloc ne selectionne pas celui de derriere.

La face touchee compte autant que le bloc : « poser un bloc » se fait CONTRE
elle, comme en jeu.
"""
from __future__ import annotations

import math

Vec = tuple[float, float, float]


def ray_from_pixel(camera, x: float, y: float, width: float,
                   height: float) -> tuple[Vec, Vec]:
    """Origine et direction (unitaire) du rayon sous le pixel (x, y).

    La base de `OrbitCamera._basis` coincide terme a terme avec celle que
    construit `lookAt` : `right` et `up` du repere de vue, `forward` pointant
    VERS la camera. Le rayon part donc de l'oeil selon `-forward`.
    """
    right, up, forward = camera._basis()
    eye = camera.eye()
    aspect = width / max(height, 1e-9)
    tan_v = math.tan(math.radians(camera.FOV) / 2.0)
    tan_h = tan_v * aspect
    nx = 2.0 * x / max(width, 1e-9) - 1.0
    ny = 1.0 - 2.0 * y / max(height, 1e-9)
    d = [-forward[i] + right[i] * nx * tan_h + up[i] * ny * tan_v
         for i in range(3)]
    norm = math.sqrt(sum(c * c for c in d)) or 1.0
    return tuple(eye), tuple(c / norm for c in d)


def pick(occupied, size, origin: Vec, direction: Vec):
    """Le premier bloc plein le long du rayon : `(pos, normale)` ou `None`.

    `occupied(pos)` dit si une case porte un bloc. La normale est celle de la
    face par laquelle le rayon est entre dans le bloc : poser un bloc contre
    elle, c'est poser en `pos + normale`.
    """
    # 1. entree dans la boite [0, size) — methode des tranches
    t_enter, t_exit = 0.0, math.inf
    entry_axis = None
    for i in range(3):
        o, d = origin[i], direction[i]
        if abs(d) < 1e-12:
            if o < 0.0 or o >= size[i]:
                return None
            continue
        t0, t1 = (0.0 - o) / d, (size[i] - o) / d
        if t0 > t1:
            t0, t1 = t1, t0
        if t0 > t_enter:
            t_enter, entry_axis = t0, i
        t_exit = min(t_exit, t1)
        if t_enter > t_exit:
            return None

    # 2. premiere case, un rien a l'interieur pour ne pas rester sur le bord
    t = t_enter + 1e-7
    voxel = [min(int(size[i]) - 1, max(0, int(math.floor(origin[i]
                                                          + direction[i] * t))))
             for i in range(3)]
    normal = [0, 0, 0]
    if entry_axis is not None:
        normal[entry_axis] = -1 if direction[entry_axis] > 0 else 1

    step, t_max, t_delta = [0, 0, 0], [math.inf] * 3, [math.inf] * 3
    for i in range(3):
        d = direction[i]
        if d > 0:
            step[i] = 1
            t_max[i] = (voxel[i] + 1 - origin[i]) / d
            t_delta[i] = 1.0 / d
        elif d < 0:
            step[i] = -1
            t_max[i] = (voxel[i] - origin[i]) / d
            t_delta[i] = -1.0 / d

    # 3. case par case, toujours par la frontiere la plus proche
    limit = int(sum(size)) * 3 + 8
    for _ in range(limit):
        if occupied(tuple(voxel)):
            return tuple(voxel), tuple(normal)
        axis = min(range(3), key=lambda k: t_max[k])
        voxel[axis] += step[axis]
        if not (0 <= voxel[axis] < size[axis]):
            return None
        normal = [0, 0, 0]
        normal[axis] = -step[axis]
        t_max[axis] += t_delta[axis]
    return None
