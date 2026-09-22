"""Le plan de sol, dessine : une grille sous le vaisseau (F2.4, F3).

Un vaisseau qu'on pose sur un sol invisible ne se pose pas, il s'arrete en
l'air. La grille donne les trois choses qui manquaient a l'oeil : ou est le
sol, a quelle distance, et sous quel angle la coque le rencontre.

Elle est volontairement pauvre — des lignes, pas une surface pleine. Une dalle
opaque cacherait le train d'atterrissage au moment precis ou on le regarde, et
une dalle transparente teinterait toutes les forces qui la traversent.

Elle vit dans le repere du MONDE : elle ne tourne pas avec le vaisseau, et le
plan de coupe ne la coupe pas.
"""
from __future__ import annotations

import numpy as np

from .mesh import Mesh

#: teinte de la grille, et de ses axes majeurs
GRID = (0.34, 0.38, 0.44)
MAJOR = (0.52, 0.58, 0.66)

#: demi-largeur du sol, en multiples de la plus grande dimension du vaisseau
SPAN = 1.6
#: pas de la grille, en blocs, choisi pour rester lisible a toutes les tailles
STEPS = (1, 2, 5, 10, 20, 50)
#: nombre de lignes visees : c'est lui qui choisit le pas
WANTED = 28
#: epaisseur d'une ligne, en blocs
WIDTH = 0.06


def _step_for(span: float) -> int:
    for step in STEPS:
        if span * 2 / step <= WANTED:
            return step
    return STEPS[-1]


def build_ground_mesh(size, centre, y: float) -> Mesh:
    """Une grille horizontale a la cote `y`, centree sous `centre`.

    `size` est la taille du vaisseau : le sol s'etend au-dela, pour qu'on voie
    toujours ou il passe meme quand la camera recule.
    """
    span = max(size) * SPAN
    step = _step_for(span)
    x0, z0 = float(centre[0]), float(centre[2])
    # les lignes tombent sur des cotes rondes : une grille qui glisse avec le
    # vaisseau ne dit plus rien de la distance parcourue
    first_x = int((x0 - span) // step) * step
    first_z = int((z0 - span) // step) * step

    quads: list[tuple[np.ndarray, tuple]] = []

    def bande(lo, hi, axis: int, colour) -> None:
        """Un rectangle horizontal mince, le long de `axis` (0 = x, 2 = z)."""
        a, b = np.array(lo, dtype=np.float32), np.array(hi, dtype=np.float32)
        wide = np.zeros(3, dtype=np.float32)
        wide[2 if axis == 0 else 0] = WIDTH
        p0, p1 = a - wide, b - wide
        p2, p3 = b + wide, a + wide
        quads.append((np.stack([p0, p1, p2, p0, p2, p3]), colour))

    x = first_x
    while x <= x0 + span:
        colour = MAJOR if x == 0 else GRID
        bande((x, y, z0 - span), (x, y, z0 + span), 2, colour)
        x += step
    z = first_z
    while z <= z0 + span:
        colour = MAJOR if z == 0 else GRID
        bande((x0 - span, y, z), (x0 + span, y, z), 0, colour)
        z += step

    if not quads:
        return Mesh()
    positions = np.concatenate([q for q, _ in quads]).astype(np.float32)
    colors = np.concatenate(
        [np.tile(np.array(c, dtype=np.float32), (len(q), 1))
         for q, c in quads]).astype(np.float32)
    normals = np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32),
                      (len(positions), 1))
    lo = (x0 - span, y, z0 - span)
    hi = (x0 + span, y, z0 + span)
    return Mesh(positions=positions.reshape(-1), normals=normals.reshape(-1),
                colors=colors.reshape(-1), quads=len(quads), bounds=(lo, hi))
