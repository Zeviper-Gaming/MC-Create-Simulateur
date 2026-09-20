"""Trainee : comptage des blocs etanches et leur barycentre.

Cout faible. Invalide seulement si le bloc touche est etanche.

Le materiau flottant `aeronautics:simple_drag` porte `floating_scale = 0,33` et
`transition_speed = 0` : il n'y a donc pas de composante « slow drag », la
trainee est purement lineaire, F = -k.v avec k = 0,33 x N x pression.
"""
from __future__ import annotations

from ..data.nbt import Pos
from .vehicle import Organ


class DragOrgan(Organ):
    name = "trainee"
    cost = "faible"

    def __init__(self, model):
        super().__init__(model)
        self.cells: set[Pos] = set()
        self.centre = (0.0, 0.0, 0.0)

    def affected_by(self, pos: Pos) -> bool:
        return pos in self.cells or self.props.is_airtight(self.s.name(pos))

    def recompute(self) -> None:
        cells: set[Pos] = set()
        for name in list(self.s.by_name):
            if self.props.is_airtight(name):
                cells |= self.s.by_name[name]
        self.cells = cells
        if cells:
            n = len(cells)
            self.centre = tuple(
                sum(p[i] + 0.5 for p in cells) / n for i in range(3))
        else:
            self.centre = (0.0, 0.0, 0.0)

    @property
    def count(self) -> int:
        return len(self.cells)

    def coefficient(self, pressure: float = 1.0) -> float:
        """k de F = -k.v, a la pression donnee."""
        scale = self.tables.get("forces.drag_floating_scale")
        return scale * len(self.cells) * pressure

    def report(self, pressure: float = 1.0) -> dict:
        return {
            "blocs_etanches": self.count,
            "coefficient": round(self.coefficient(pressure), 3),
            "coefficient_niveau_mer": round(self.coefficient(1.0), 2),
            "centre": [round(v, 2) for v in self.centre],
            "modele": "lineaire F = -k.v",
        }
