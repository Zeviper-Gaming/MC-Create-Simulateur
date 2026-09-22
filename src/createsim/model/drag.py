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
        #: sommes de r_i.r_j sur les cases etanches, a l'origine. Un vaisseau
        #: qui tourne voit chacune d'elles balayer l'air : le couple resistant
        #: a la meme forme qu'un tenseur d'inertie, pondere par la trainee.
        self.products = [0.0] * 6

    def affected_by(self, pos: Pos) -> bool:
        return pos in self.cells or self.props.is_airtight(self.s.name(pos))

    def recompute(self) -> None:
        cells: set[Pos] = set()
        for name in list(self.s.by_name):
            if self.props.is_airtight(name):
                cells |= self.s.by_name[name]
        self.cells = cells
        products = [0.0] * 6
        for pos in cells:
            x, y, z = pos[0] + 0.5, pos[1] + 0.5, pos[2] + 0.5
            products[0] += x * x
            products[1] += y * y
            products[2] += z * z
            products[3] += x * y
            products[4] += x * z
            products[5] += y * z
        self.products = products
        if cells:
            n = len(cells)
            self.centre = tuple(
                sum(p[i] + 0.5 for p in cells) / n for i in range(3))
        else:
            self.centre = (0.0, 0.0, 0.0)

    @property
    def count(self) -> int:
        return len(self.cells)

    def envelope_coefficient(self, pressure: float = 1.0) -> float:
        """k de l'enveloppe seule, a la pression donnee.

        Le moteur somme le `floating_scale` bloc par bloc (`totalScale`) ; tous
        les blocs etanches portant 0,33, la somme se reduit ici a un produit.
        """
        scale = self.tables.get("forces.drag_floating_scale")
        return scale * len(self.cells) * pressure

    def universal_coefficient(self, mass: float) -> float:
        """k equivalent de l'amortissement universel du moteur physique.

        Rapier recoit `universal_drag` comme un TAUX par seconde applique a la
        vitesse du corps : `v <- v / (1 + dt.c)`. Mon amortissement entre comme
        un coefficient de force, ou le taux vaut k/m — d'ou la masse.

        C'est le terme qui manquait, et il ne manquait pas d'un peu : sur le
        c1_air_cruiser, 20 659 blocs pour 839 etanches, il divise la constante
        de temps par 6,4.
        """
        return self.tables.get("pressure.universal_drag") * mass

    def coefficient(self, pressure: float = 1.0, mass: float = 0.0) -> float:
        """k total de F = -k.v : enveloppe + amortissement universel."""
        return self.envelope_coefficient(pressure) + self.universal_coefficient(mass)

    def report(self, pressure: float = 1.0, mass: float = 0.0) -> dict:
        enveloppe = self.envelope_coefficient(pressure)
        universel = self.universal_coefficient(mass)
        return {
            "blocs_etanches": self.count,
            "coefficient": round(enveloppe + universel, 3),
            "coefficient_enveloppe": round(enveloppe, 3),
            "coefficient_universel": round(universel, 3),
            "coefficient_niveau_mer": round(self.envelope_coefficient(1.0), 2),
            "centre": [round(v, 2) for v in self.centre],
            "modele": "lineaire F = -k.v, enveloppe + amortissement Rapier",
        }
