"""Maillage par troncons : ne refaire que ce qu'une edition a touche (F6.4).

Remailler tout le c1_air_cruiser coute 219 ms. Un tick en dure 50 : chaque
edition figerait l'image un cinquieme de seconde, et le cahier exige que les
grandeurs se mettent a jour « sans interruption perceptible ».

La reponse est celle de tous les moteurs voxel : decouper la structure en
troncons de 16 blocs de cote et ne remailler que ceux dont une case a change —
plus leurs voisins, parce qu'une face au bord d'un troncon depend de la case
d'a cote. Le prix est connu et faible : la fusion gloutonne s'arrete aux
frontieres, donc un peu plus de triangles.

Ce qui a change se lit par DIFFERENCE de grilles, pas en devinant : une edition
change aussi la famille de blocs qu'elle n'a pas touches (retirer un arbre de
transmission sort ses voisins du reseau cinetique, et leur couleur change).
"""
from __future__ import annotations

import numpy as np

from .mesh import (Mesh, build_region, concat_meshes, exposure_masks,
                   family_grid)

SIX = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


class ChunkedMesh:
    """La structure, maillee troncon par troncon, et tenue a jour."""

    SIDE = 16

    def __init__(self, structure, family_at, palette=None):
        self.palette = palette
        self.grid, self.size = family_grid(structure, family_at)
        self.masks = exposure_masks(self.grid)
        self.chunks: dict[tuple[int, int, int], Mesh] = {}
        for chunk in self._all_chunks():
            self.chunks[chunk] = self._build(chunk)
        self._mesh: Mesh | None = None
        self.last_rebuilt: set = set(self.chunks)

    # -- geometrie des troncons -------------------------------------------
    def _all_chunks(self):
        counts = [max(1, -(-int(s) // self.SIDE)) for s in self.size]
        for cx in range(counts[0]):
            for cy in range(counts[1]):
                for cz in range(counts[2]):
                    yield (cx, cy, cz)

    def chunk_of(self, pos) -> tuple[int, int, int]:
        return tuple(int(pos[i]) // self.SIDE for i in range(3))

    def _bounds(self, chunk):
        lo = tuple(chunk[i] * self.SIDE for i in range(3))
        hi = tuple(min(lo[i] + self.SIDE, int(self.size[i])) for i in range(3))
        return lo, hi

    def _build(self, chunk) -> Mesh:
        lo, hi = self._bounds(chunk)
        return build_region(self.masks, self.size, lo, hi, self.palette)

    def _inside(self, pos) -> bool:
        return all(0 <= pos[i] < self.size[i] for i in range(3))

    # -- mise a jour --------------------------------------------------------
    def update(self, structure, family_at, positions=None) -> set:
        """Remaille ce qui a change depuis la derniere fois. Renvoie les
        troncons refaits — vide si l'edition n'a rien change a l'image.

        `positions` : les cases editees, quand on sait que la couleur d'aucune
        autre n'a pu changer. Recalculer la famille des 20 659 blocs du
        cruiser coute 12 ms ; c'est inutile sauf si le reseau cinetique a ete
        refait — retirer un arbre sort ses voisins du reseau, et leur couleur
        change sans qu'on les ait touches. L'appelant decide.
        """
        if positions is not None and tuple(structure.size) == tuple(self.size):
            from .mesh import FAMILY_INDEX
            grid = self.grid.copy()
            for pos in positions:
                if not self._inside(pos):
                    continue
                block = structure.blocks.get(pos)
                grid[pos] = (-1 if block is None or structure.is_air(pos)
                             else FAMILY_INDEX.get(family_at(pos, block), 0))
            size = self.size
        else:
            grid, size = family_grid(structure, family_at)
        if tuple(size) != tuple(self.size):
            self.__init__(structure, family_at, self.palette)
            return set(self.chunks)
        changed = np.argwhere(grid != self.grid)
        self.last_rebuilt = set()
        if not len(changed):
            return set()
        self.grid = grid
        self.masks = exposure_masks(grid)
        dirty: set = set()
        for x, y, z in changed:
            for dx, dy, dz in ((0, 0, 0),) + SIX:
                pos = (x + dx, y + dy, z + dz)
                if self._inside(pos):
                    dirty.add(self.chunk_of(pos))
        for chunk in dirty:
            self.chunks[chunk] = self._build(chunk)
        self._mesh = None
        self.last_rebuilt = dirty
        return dirty

    def mesh(self) -> Mesh:
        """Le tampon complet, recolle. Garde en cache jusqu'a la prochaine
        edition : a vitesse de simulation, rien ne le change."""
        if self._mesh is None:
            self._mesh = concat_meshes(
                (self.chunks[c] for c in sorted(self.chunks)), self.size,
                int((self.grid >= 0).sum()))
        return self._mesh

    # -- ce que la selection a besoin de savoir -----------------------------
    def occupied(self, pos) -> bool:
        return self._inside(pos) and bool(self.grid[tuple(pos)] >= 0)
