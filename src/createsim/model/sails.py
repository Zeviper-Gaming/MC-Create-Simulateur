"""Les voiles de coque : celles qui font portance, et non celles d'un rotor.

Decouverte au bytecode : Sable expose `BlockSubLevelLiftProvider`, et le mixin
qui y branche les voiles de Create s'appelle en toutes lettres
`mixin.compatibility.create.sails_providing_lift`. Les ponders de Simulated le
confirment — « When moving on a Simulated Contraption, Regular Sails provide
Lift », « applied perpendicular to its surface ».

    voile Create      portance 0,475   trainee ∥ 0,75   trainee diffuse 0,0689
    voile symetrique  portance 0       trainee ∥ 1,75   trainee diffuse 0,0689

Seules comptent ici les voiles de COQUE. Celles d'un rotor de palier tournent
avec lui : leur vitesse n'est pas celle du vaisseau, et leur effet est deja
porte par le moulin ou l'helice. Les confondre ferait compter 174 voiles de
portance sur un cachalot qui n'en a aucune hors de son moulin.
"""
from __future__ import annotations

from ..data.nbt import Pos
from .vehicle import Organ

FACING_VEC = {"east": (1.0, 0.0, 0.0), "west": (-1.0, 0.0, 0.0),
              "up": (0.0, 1.0, 0.0), "down": (0.0, -1.0, 0.0),
              "south": (0.0, 0.0, 1.0), "north": (0.0, 0.0, -1.0)}
OPPOSITE = {"east": "west", "west": "east", "up": "down", "down": "up",
            "south": "north", "north": "south"}
#: `Direction.get(AxisDirection.POSITIVE, axis)`
POSITIVE = {"x": "east", "y": "up", "z": "south"}


def sail_normal(props: dict, symmetric: bool) -> str | None:
    """La normale d'une voile, comme `sable$getNormal` la calcule.

    Les deux familles ne la portent pas au meme endroit, et les confondre
    envoyait la trainee des voiles symetriques sur le mauvais axe :

        voile Create      FACING.getOpposite()
        voile symetrique  Direction.get(POSITIVE, AXIS)    — pas de facing

    Pour une voile symetrique le signe est sans effet : elle ne porte pas, et
    la trainee parallele n (n . v) est quadratique en n.
    """
    if symmetric:
        return POSITIVE.get(props.get("axis", ""))
    facing = props.get("facing")
    return OPPOSITE.get(facing, facing)


class Sail:
    """Une voile de coque : sa normale, sa position, sa famille."""

    __slots__ = ("pos", "normal", "symmetric")

    def __init__(self, pos: Pos, normal: str | None, symmetric: bool):
        self.pos = pos
        self.normal = normal
        self.symmetric = symmetric

    @property
    def axis(self) -> int:
        vec = FACING_VEC.get(self.normal or "", (0.0, 1.0, 0.0))
        return max(range(3), key=lambda i: abs(vec[i]))

    @property
    def vector(self) -> tuple[float, float, float]:
        return FACING_VEC.get(self.normal or "", (0.0, 1.0, 0.0))


class SailOrgan(Organ):
    """Cout faible : un balayage des voiles, moins celles des rotors."""

    name = "voiles"
    cost = "faible"
    depends = ("paliers",)

    def __init__(self, model):
        super().__init__(model)
        self.sails: list[Sail] = []
        self.positions: frozenset[Pos] = frozenset()
        self.centre = (0.0, 0.0, 0.0)

    def affected_by(self, pos: Pos) -> bool:
        # La position AVANT le nom : une voile supprimee est devenue de l'air,
        # et ne regarder que le nom laissait l'organe compter une voile fantome.
        if pos in self.positions:
            return True
        name = self.s.name(pos)
        return (self.props.is_sail(name)
                or name in self.tables.get("forces.symmetric_sail_blocks"))

    def recompute(self) -> None:
        symmetric_blocks = frozenset(
            self.tables.get("forces.symmetric_sail_blocks"))
        rotor: set[Pos] = set()
        for bearing in self.model.organs["paliers"].bearings:
            rotor |= bearing.rotor

        self.sails = []
        for pos, block in self.s:
            name = block["name"]
            symmetric = name in symmetric_blocks
            if not symmetric and not self.props.is_sail(name):
                continue
            if pos in rotor:
                continue
            self.sails.append(Sail(pos, sail_normal(block["props"], symmetric),
                                   symmetric))
        self.sails.sort(key=lambda s: s.pos)
        self.positions = frozenset(s.pos for s in self.sails)

        if self.sails:
            n = len(self.sails)
            self.centre = tuple(
                sum(s.pos[i] + 0.5 for s in self.sails) / n for i in range(3))
        else:
            self.centre = (0.0, 0.0, 0.0)

    @property
    def count(self) -> int:
        return len(self.sails)

    def report(self) -> dict:
        symetriques = sum(1 for s in self.sails if s.symmetric)
        return {
            "voiles_de_coque": self.count,
            "dont_symetriques": symetriques,
            "centre": [round(v, 2) for v in self.centre],
            "note": ("les voiles d'un rotor de palier sont exclues : leur "
                     "vitesse n'est pas celle du vaisseau"),
        }
