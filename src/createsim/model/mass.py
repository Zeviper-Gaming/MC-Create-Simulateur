"""Masse, centre de masse, tenseur d'inertie, et la barre d'erreur.

Cout negligeable : mise a jour differentielle, invalide a chaque edition.

F1.5 n'est pas cosmetique. Un fichier peut contenir des blocs de mods que
l'utilisateur n'a pas ; ils retombent sur la masse par defaut de 1,0 et faussent
silencieusement tout le bilan. Le compte des blocs hors table est la barre
d'erreur affichee a cote du ratio portance/poids.
"""
from __future__ import annotations

from collections import Counter

from ..data.nbt import Pos
from .vehicle import Edit, Organ


class MassOrgan(Organ):
    name = "masse"
    cost = "negligeable"

    def __init__(self, model):
        super().__init__(model)
        self.total = 0.0
        self.moments = [0.0, 0.0, 0.0]
        #: somme de m.r_i.r_j, dans l'ordre xx, yy, zz, xy, xz, yz, prise a
        #: l'ORIGINE de la structure. Le theoreme des axes paralleles ramene
        #: ensuite le tenseur au centre de masse, qui bouge a chaque edition —
        #: accumuler autour de lui obligerait a tout reprendre.
        self.products = [0.0] * 6
        #: somme des inerties PROPRES des blocs, diagonale
        self.own = [0.0] * 3
        self.per_block: Counter = Counter()
        self.unknown: Counter = Counter()

    def affected_by(self, pos: Pos) -> bool:
        return True

    @property
    def com(self) -> tuple[float, float, float]:
        if self.total <= 0:
            return (0.0, 0.0, 0.0)
        return tuple(m / self.total for m in self.moments)

    @property
    def unknown_total(self) -> int:
        return sum(self.unknown.values())

    def recompute(self) -> None:
        total = 0.0
        mx = my = mz = 0.0
        products = [0.0] * 6
        own = [0.0] * 3
        per: Counter = Counter()
        unknown: Counter = Counter()
        mass_of = self.props.mass
        known = self.props.is_known_namespace
        cube = 1.0 / 6.0
        for pos, b in self.s.blocks.items():
            name = b["name"]
            if not known(name):
                unknown[name] += 1
            m = mass_of(name)
            if m <= 0:
                continue
            x, y, z = pos[0] + 0.5, pos[1] + 0.5, pos[2] + 0.5
            total += m
            mx += x * m
            my += y * m
            mz += z * m
            products[0] += m * x * x
            products[1] += m * y * y
            products[2] += m * z * z
            products[3] += m * x * y
            products[4] += m * x * z
            products[5] += m * y * z
            spin = m * cube
            own[0] += spin
            own[1] += spin
            own[2] += spin
            per[name] += m
        self.total = total
        self.moments = [mx, my, mz]
        self.products = products
        self.own = own
        self.per_block = per
        self.unknown = unknown

    # -- inertie (F2.3) ----------------------------------------------------
    def inertia(self) -> list[list[float]]:
        """Le tenseur d'inertie AU CENTRE DE MASSE, tire de la geometrie.

        Les sommes sont tenues a l'origine ; le theoreme des axes paralleles
        les y ramene. Chaque bloc porte en plus son inertie propre de cube,
        m/6 sur chaque axe : negligeable devant le terme de bras des qu'un
        vaisseau depasse quelques blocs, mais gratuite a compter.

        Sable ne declare une inertie particuliere que pour `create:flywheel`
        (un disque, 2,25 / 1,125 / 1,125 pour 4 de masse au lieu de 0,67) :
        l'ecart pese moins de 0,01 % du tenseur d'un vaisseau, et il est
        signale comme limite du modele plutot que tu.
        """
        xx, yy, zz, xy, xz, yz = self.products
        trace = xx + yy + zz
        tensor = [[trace - xx, -xy, -xz],
                  [-xy, trace - yy, -yz],
                  [-xz, -yz, trace - zz]]
        # ramener au centre de masse : I_com = I_origine - M (|c|^2 E - c x c)
        m = self.total
        if m > 0:
            c = self.com
            c2 = c[0] * c[0] + c[1] * c[1] + c[2] * c[2]
            for i in range(3):
                for j in range(3):
                    shift = (c2 if i == j else 0.0) - c[i] * c[j]
                    tensor[i][j] -= m * shift
        for i in range(3):
            tensor[i][i] += self.own[i]
        return tensor

    def apply_delta(self, edits: list[Edit]) -> bool:
        for e in edits:
            self._contribute(e.pos, e.before, -1)
            self._contribute(e.pos, e.after, +1)
        if self.total < -1e-6:
            return False          # derive : on refait proprement
        self.total = max(self.total, 0.0)
        return True

    def _contribute(self, pos: Pos, entry: dict | None, sign: int) -> None:
        if entry is None:
            return
        name = entry["name"]
        if not self.props.is_known_namespace(name):
            self.unknown[name] += sign
            if self.unknown[name] <= 0:
                del self.unknown[name]
        m = self.props.mass(name)
        if m <= 0:
            return
        m *= sign
        self.total += m
        x, y, z = pos[0] + 0.5, pos[1] + 0.5, pos[2] + 0.5
        for i in range(3):
            self.moments[i] += (pos[i] + 0.5) * m
        self.products[0] += m * x * x
        self.products[1] += m * y * y
        self.products[2] += m * z * z
        self.products[3] += m * x * y
        self.products[4] += m * x * z
        self.products[5] += m * y * z
        spin = m / 6.0
        for i in range(3):
            self.own[i] += spin
        self.per_block[name] += m
        if abs(self.per_block[name]) < 1e-12:
            del self.per_block[name]

    def report(self) -> dict:
        com = self.com
        tensor = self.inertia()
        return {
            "masse": round(self.total, 2),
            "centre_de_masse": [round(v, 2) for v in com],
            "inertie": [[round(v, 1) for v in row] for row in tensor],
            "blocs_hors_table": {
                "total": self.unknown_total,
                "detail": self.unknown.most_common(10),
                "incertitude": (
                    "ces blocs retombent sur la masse par defaut de 1,0 ; "
                    "le ratio portance/poids en depend directement"
                    if self.unknown else None),
            },
        }
