"""La peau du vaisseau : les points par lesquels il peut toucher le sol.

Jusqu'ici le sol etait un plancher sous le CENTRE DE MASSE, avec l'hypothese
implicite que le bas de la coque se trouvait a la cote 0 de la structure. Un
vaisseau dont le premier bloc est plus haut s'enfoncait donc dans le sol, et un
vaisseau penche ne touchait jamais par son point le plus bas.

Ce qu'il faut pour poser un vaisseau, c'est sa peau : l'ensemble des sommets
susceptibles de toucher un plan, quelle que soit son assiette. Sous une
rotation quelconque, le point le plus bas d'un solide est un sommet de son
enveloppe ; il suffit donc de garder les huit coins des blocs EXPOSES — un coin
enferme a l'interieur de la coque ne peut jamais etre le plus bas.

Le calcul est PARESSEUX : tant que personne n'allume le plan de sol, il ne
coute rien, et une edition se contente de jeter le cache.
"""
from __future__ import annotations

import numpy as np

from ..data.nbt import Pos, SIX
from .vehicle import Organ

#: les huit coins d'un bloc, en coordonnees locales
CORNERS = tuple((dx, dy, dz)
                for dx in (0.0, 1.0) for dy in (0.0, 1.0) for dz in (0.0, 1.0))


class HullOrgan(Organ):
    """Les sommets de la coque, pour le contact avec le sol."""

    name = "coque"
    cost = "faible"

    def __init__(self, model):
        super().__init__(model)
        self._points: np.ndarray | None = None
        self.exposed = 0

    # -- invalidation ------------------------------------------------------
    def affected_by(self, pos: Pos) -> bool:
        """Toute edition peut changer la peau : poser un bloc en enferme un
        autre, en retirer un en expose six. Mais l'invalidation ne coute qu'un
        cache jete — le recalcul, lui, attend qu'on en ait besoin."""
        return True

    def recompute(self) -> None:
        self._points = None
        self.exposed = 0

    def apply_delta(self, edits) -> bool:
        self.recompute()
        return True

    def digest(self):
        return (self.exposed,)

    # -- la peau, calculee au premier besoin --------------------------------
    @property
    def points(self) -> np.ndarray:
        if self._points is None:
            self._points = self._build()
        return self._points

    def _build(self) -> np.ndarray:
        blocks = self.s.blocks
        corners: set[tuple[float, float, float]] = set()
        exposed = 0
        has_collision = self.props.has_collision
        for pos, entry in blocks.items():
            if not has_collision(entry["name"]):
                continue
            for d in SIX:
                q = (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])
                if q not in blocks:
                    break
            else:
                continue                       # bloc enferme : jamais en contact
            exposed += 1
            for c in CORNERS:
                corners.add((pos[0] + c[0], pos[1] + c[1], pos[2] + c[2]))
        self.exposed = exposed
        if not corners:
            return np.zeros((0, 3), dtype=float)
        return np.asarray(sorted(corners), dtype=float)

    def lowest_local(self) -> float:
        """La cote du point le plus bas, vaisseau a plat. Sert a poser un
        vaisseau au ras du sol sans le calculer bloc a bloc."""
        pts = self.points
        return float(pts[:, 1].min()) if len(pts) else 0.0

    def report(self) -> dict:
        pts = self.points
        return {
            "blocs_exposes": self.exposed,
            "sommets_de_contact": int(len(pts)),
            "bas_de_coque": round(self.lowest_local(), 2) if len(pts) else None,
        }
