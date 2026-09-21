"""Les supports de roue Offroad : suspension, axes, masse portee.

Releve au bytecode de `WheelMountBlockEntity.sable$physicsTick`, offsets 100 a
170 (`offroad-neoforge-1.21.1-1.3.1.jar`) :

    normalMass        = 1 / massTracker.getInverseNormalMass(contact, UP)
    stiffness         = molette du support (ScrollValue)
    normalMassScaling = min(normalMass / stiffness, 1) x 10
    strengthMul       = stiffness x normalMassScaling x 2

Le tout se simplifie en `strengthMul = 20 x min(masse_portee, raideur)`, et ce
n'est pas qu'une reecriture : sous saturation la deceleration vaut
`20 x coef x v`, INDEPENDANTE DE LA MASSE, comme le frottement reel. Au-dela,
`strengthMul` plafonne a `20 x raideur` et la deceleration devient inversement
proportionnelle a la masse — autrement dit, un vehicule surcharge sur
suspension molle ne freine plus.

`normalMass` est la masse effective au point de contact selon la verticale,
tiree de la matrice de masse inverse du corps. Le simulateur n'a pas de tenseur
d'inertie complet avant L6 : il repartit la masse a parts egales entre les
roues et le DIT (F5.10), plutot que de livrer un chiffre faux en silence.
"""
from __future__ import annotations

from ..data.nbt import Pos
from .vehicle import Organ

#: axes du monde, par lettre
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}

FACING_VEC = {"east": (1.0, 0.0, 0.0), "west": (-1.0, 0.0, 0.0),
              "up": (0.0, 1.0, 0.0), "down": (0.0, -1.0, 0.0),
              "south": (0.0, 0.0, 1.0), "north": (0.0, 0.0, -1.0)}

#: l'axe horizontal perpendiculaire, pour la derive laterale
PERPENDICULAR = {"east": "z", "west": "z", "south": "x", "north": "x"}

SIX = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


class Wheel:
    """Un support de roue, avec ses axes et sa suspension."""

    __slots__ = ("pos", "facing", "stiffness", "tire", "radius",
                 "normal_mass", "strength_mul", "saturated")

    def __init__(self, pos: Pos, facing: str | None, stiffness: float,
                 tire: str | None, radius: float):
        self.pos = pos
        self.facing = facing
        self.stiffness = stiffness
        self.tire = tire
        self.radius = radius
        self.normal_mass = 0.0
        self.strength_mul = 0.0
        self.saturated = False

    @property
    def longitudinal(self) -> tuple[float, float, float]:
        return FACING_VEC.get(self.facing or "", (0.0, 0.0, 1.0))

    @property
    def longitudinal_axis(self) -> int:
        vec = self.longitudinal
        return max(range(3), key=lambda i: abs(vec[i]))

    @property
    def lateral_axis(self) -> int:
        letter = PERPENDICULAR.get(self.facing or "")
        return AXIS_INDEX[letter] if letter else 0

    def report(self) -> dict:
        return {
            "pos": list(self.pos),
            "orientation": self.facing,
            "pneu": self.tire,
            "rayon": self.radius,
            "raideur": self.stiffness,
            "masse_portee": round(self.normal_mass, 2),
            "strength_mul": round(self.strength_mul, 1),
            "suspension_saturee": self.saturated,
        }


class WheelOrgan(Organ):
    """Cout negligeable : quelques blocs, une division par leur nombre."""

    name = "roues"
    cost = "negligeable"
    depends = ("masse",)

    def __init__(self, model):
        super().__init__(model)
        self.wheels: list[Wheel] = []
        self.sensitive: frozenset[Pos] = frozenset()

    def affected_by(self, pos: Pos) -> bool:
        # un support pose la ou il n'y en avait pas, ou la molette / le signal
        # d'un support existant (ils arrivent par les faces voisines)
        return (pos in self.sensitive
                or self.s.name(pos) in self.tables.get("forces.wheel_mount_blocks"))

    def recompute(self) -> None:
        radii = self.tables.get("forces.tire_radii")
        default_stiffness = self.tables.get("forces.wheel_default_stiffness")
        factor = self.tables.get("forces.wheel_strength_mul_factor")

        self.wheels = []
        for name in self.tables.get("forces.wheel_mount_blocks"):
            for pos in sorted(self.s.positions_of(name)):
                block = self.s.blocks[pos]
                nbt = block.get("nbt") or {}
                tire = _tire_of(nbt)
                self.wheels.append(Wheel(
                    pos, block["props"].get("facing"),
                    float(nbt.get("ScrollValue") or default_stiffness),
                    tire, float(radii.get(_short(tire), radii.get("tire", 1.0)))))

        # masse portee : a parts egales, faute de tenseur d'inertie (L6)
        total = self.model.organs["masse"].total if self.wheels else 0.0
        share = total / len(self.wheels) if self.wheels else 0.0
        for wheel in self.wheels:
            wheel.normal_mass = share
            wheel.saturated = share > wheel.stiffness
            wheel.strength_mul = factor * min(share, wheel.stiffness)

        sensitive: set[Pos] = set()
        for wheel in self.wheels:
            sensitive.add(wheel.pos)
            for d in SIX:
                sensitive.add((wheel.pos[0] + d[0], wheel.pos[1] + d[1],
                               wheel.pos[2] + d[2]))
        self.sensitive = frozenset(sensitive)

    @property
    def count(self) -> int:
        return len(self.wheels)

    def report(self) -> list[dict]:
        return [w.report() for w in self.wheels]


def _tire_of(nbt: dict) -> str | None:
    item = nbt.get("HeldItem") or nbt.get("Item") or {}
    return item.get("id") if isinstance(item, dict) else None


def _short(tire: str | None) -> str:
    return (tire or "tire").split(":")[-1]
