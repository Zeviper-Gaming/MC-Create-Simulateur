"""Blocs de levitite : sustentation par bloc, plafonnee a la flottaison neutre.

Cout faible, comptage. Invalide si le bloc touche est de la levitite.

`prevent_self_lift` est actif : la sustentation ne peut jamais accelerer le
vehicule vers le haut, elle se contente d'annuler le poids. Un vaisseau qui a
plus de levitite qu'il n'en faut ne monte pas — il flotte.
"""
from __future__ import annotations

from ..data.nbt import Pos
from .vehicle import Organ


class LevititeOrgan(Organ):
    name = "levitite"
    cost = "faible"

    def __init__(self, model):
        super().__init__(model)
        self.cells: set[Pos] = set()
        self.centre = (0.0, 0.0, 0.0)

    def affected_by(self, pos: Pos) -> bool:
        return pos in self.cells or self.props.is_levitite(self.s.name(pos))

    def recompute(self) -> None:
        cells: set[Pos] = set()
        for name in list(self.s.by_name):
            if self.props.is_levitite(name):
                cells |= self.s.by_name[name]
        self.cells = cells
        if cells:
            n = len(cells)
            self.centre = tuple(sum(p[i] + 0.5 for p in cells) / n for i in range(3))
        else:
            self.centre = (0.0, 0.0, 0.0)

    @property
    def raw_lift(self) -> float:
        """Portance brute, en equivalent masse."""
        return len(self.cells) * self.tables.get("forces.levitite_lift_strength")

    def effective_lift(self, total_mass: float) -> float:
        raw = self.raw_lift
        if self.tables.get("forces.levitite_prevent_self_lift"):
            return min(raw, total_mass)
        return raw

    def report(self, total_mass: float) -> dict | None:
        if not self.cells:
            return None
        raw = self.raw_lift
        return {
            "blocs": len(self.cells),
            "portance_brute": raw,
            "portance_effective": self.effective_lift(total_mass),
            "plafonnee": raw > total_mass,
            "centre": [round(v, 2) for v in self.centre],
            "marge": round(raw - total_mass, 2),
        }
