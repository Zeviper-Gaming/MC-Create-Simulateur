"""Masse, centre de masse, et la barre d'erreur qui va avec.

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
        per: Counter = Counter()
        unknown: Counter = Counter()
        mass_of = self.props.mass
        known = self.props.is_known_namespace
        for pos, b in self.s.blocks.items():
            name = b["name"]
            if not known(name):
                unknown[name] += 1
            m = mass_of(name)
            if m <= 0:
                continue
            total += m
            mx += (pos[0] + 0.5) * m
            my += (pos[1] + 0.5) * m
            mz += (pos[2] + 0.5) * m
            per[name] += m
        self.total = total
        self.moments = [mx, my, mz]
        self.per_block = per
        self.unknown = unknown

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
        for i in range(3):
            self.moments[i] += (pos[i] + 0.5) * m
        self.per_block[name] += m
        if abs(self.per_block[name]) < 1e-12:
            del self.per_block[name]

    def report(self) -> dict:
        com = self.com
        return {
            "masse": round(self.total, 2),
            "centre_de_masse": [round(v, 2) for v in com],
            "blocs_hors_table": {
                "total": self.unknown_total,
                "detail": self.unknown.most_common(10),
                "incertitude": (
                    "ces blocs retombent sur la masse par defaut de 1,0 ; "
                    "le ratio portance/poids en depend directement"
                    if self.unknown else None),
            },
        }
