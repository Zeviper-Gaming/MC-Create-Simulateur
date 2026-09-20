"""Paliers : le rotor, son comptage de voiles, et ses contacts avec la coque.

Cout moyen : parcours borne. Invalide si le bloc touche est dans le demi-espace
avant d'un palier.

Port de `Contraption.moveBlock` + `BlockMovementChecks` : la propagation prend
tous les blocs voisins, sauf un bloc « brittle » qui n'est pas accroche dans la
direction d'ou l'on vient.

Le rotor est borne au demi-espace situe devant le palier. Sans cette borne, un
seul bloc de contact avec la coque fait deborder le parcours sur tout le
vaisseau et rend le comptage de voiles inutilisable. Le debordement est signale
a part plutot que d'invalider le resultat — mais le comptage reste une
heuristique, et le drapeau de fiabilite doit etre reaffiche apres toute edition
proche d'un palier (F6.9).
"""
from __future__ import annotations

from collections import deque

from ..data.nbt import Pos, SIX
from .vehicle import Organ

BEARINGS = ("aeronautics:propeller_bearing",
            "aeronautics:gyroscopic_propeller_bearing",
            "create:windmill_bearing")

FACING_VEC = {"east": (1, 0, 0), "west": (-1, 0, 0), "up": (0, 1, 0),
              "down": (0, -1, 0), "south": (0, 0, 1), "north": (0, 0, -1)}
OPPOSITE_DIR = {(1, 0, 0): "west", (-1, 0, 0): "east", (0, 1, 0): "down",
                (0, -1, 0): "up", (0, 0, 1): "north", (0, 0, -1): "south"}
OPPOSITE_NAME = {"east": "west", "west": "east", "up": "down", "down": "up",
                 "north": "south", "south": "north"}

BRITTLE_EXACT = frozenset((
    "minecraft:ladder", "minecraft:torch", "minecraft:wall_torch",
    "minecraft:soul_torch", "minecraft:soul_wall_torch",
    "minecraft:redstone_torch", "minecraft:redstone_wall_torch",
    "minecraft:lever", "minecraft:redstone_wire", "minecraft:repeater",
    "minecraft:comparator", "minecraft:cocoa", "minecraft:flower_pot",
    "minecraft:moss_carpet", "minecraft:vine", "minecraft:cake",
    "minecraft:bell", "create:redstone_link", "create:nozzle",
    "create:hand_crank", "create:rope", "create:pulley_magnet",
    "create:peculiar_bell", "create:haunted_bell",
    "simulated:rope_connector", "simulated:spring",
    "simulated:directional_linked_receiver",
    "simulated:modulating_linked_receiver",
    "create:analog_lever", "simulated:throttle_lever",
))
BRITTLE_SUFFIX = ("_sign", "_wall_sign", "_hanging_sign", "_pressure_plate",
                  "_button", "_rail", "_carpet", "_door", "_bed", "_banner",
                  "_valve_handle", "_handle")


def is_brittle(name: str, props: dict) -> bool:
    if name in BRITTLE_EXACT or name.endswith(BRITTLE_SUFFIX):
        return True
    return "hanging" in props


def attached_towards(name: str, props: dict, direction: str) -> bool:
    """BlockMovementChecks.isBlockAttachedTowardsFallback, cas utiles."""
    facing = props.get("facing")
    if name == "minecraft:ladder" or name.endswith("_wall_sign"):
        return facing == OPPOSITE_NAME.get(direction)
    if name.endswith("wall_torch"):
        return facing == OPPOSITE_NAME.get(direction)
    if name == "create:redstone_link":
        return OPPOSITE_NAME.get(direction) == facing
    if name.endswith("_door"):
        return (direction == "up" if props.get("half") == "lower"
                else direction == "down")
    face = props.get("face")
    if face:
        if face == "ceiling":
            return direction == "up"
        if face == "floor":
            return direction == "down"
        return OPPOSITE_NAME.get(direction) == facing
    if "hanging" in props:
        return direction == ("up" if props["hanging"] == "true" else "down")
    return direction == "down"


class Bearing:
    __slots__ = ("pos", "name", "facing", "step", "start", "rotor", "sails",
                 "contacts", "reliable", "assembled", "last_generated")

    def __init__(self, pos: Pos, name: str, facing: str | None,
                 assembled: bool = False, last_generated: float = 0.0):
        self.pos = pos
        self.name = name
        self.facing = facing
        self.step = FACING_VEC.get(facing) if facing else None
        self.start: Pos | None = None
        self.rotor: set[Pos] = set()
        self.sails = 0
        self.contacts: list[dict] = []
        self.reliable = True
        # `Running: 1` : la contraption est assemblee, donc ses blocs ne sont
        # PLUS dans le fichier de structure. Le compte de voiles est alors
        # inconnaissable, et `LastGenerated` est la seule verite disponible.
        self.assembled = assembled
        self.last_generated = last_generated

    @property
    def sails_known(self) -> bool:
        return not self.assembled

    def in_front(self, q: Pos) -> bool:
        if self.step is None or self.start is None:
            return False
        s, st = self.start, self.step
        return sum((q[i] - s[i]) * st[i] for i in range(3)) >= 0

    def report(self) -> dict:
        out = {
            "pos": list(self.pos), "bloc": self.name, "orientation": self.facing,
            "voiles": None if self.assembled else self.sails,
            "blocs_rotor": len(self.rotor),
            "comptage_fiable": self.reliable and not self.assembled,
            "contacts_coque": self.contacts[:3],
            "assemble": self.assembled,
            "fiabilite": (
                None if (self.reliable and not self.assembled) else
                "heuristique bornee au demi-espace avant : le comptage des "
                "voiles peut etre un majorant"),
        }
        if self.assembled:
            out["regime_du_jeu"] = self.last_generated
            out["fiabilite"] = (
                "rotor assemble : ses blocs ne sont pas dans le fichier de "
                "structure. Les voiles sont inconnaissables et le regime est "
                "repris de la mesure du jeu (LastGenerated). Limite du format, "
                "pas defaut du vaisseau.")
        return out


class BearingOrgan(Organ):
    name = "paliers"
    cost = "moyen"
    LIMIT = 6000

    def __init__(self, model):
        super().__init__(model)
        self.bearings: list[Bearing] = []

    def affected_by(self, pos: Pos) -> bool:
        for b in self.bearings:
            if b.in_front(pos) or pos in b.rotor:
                return True
            for d in SIX:
                if (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2]) in b.rotor:
                    return True
        # un palier pose la ou il n'y en avait pas
        return self.s.name(pos) in BEARINGS

    def recompute(self) -> None:
        self.bearings = []
        for name in BEARINGS:
            for pos in sorted(self.s.positions_of(name)):
                block = self.s.blocks[pos]
                nbt = block.get("nbt") or {}
                b = Bearing(pos, name, block["props"].get("facing"),
                            assembled=bool(nbt.get("Running")),
                            last_generated=float(nbt.get("LastGenerated") or 0.0))
                if not b.assembled:
                    self._trace(b)
                self.bearings.append(b)
        self.bearings.sort(key=lambda b: b.pos)

    def of_type(self, name: str) -> list[Bearing]:
        return [b for b in self.bearings if b.name == name]

    def at(self, pos: Pos) -> Bearing | None:
        for b in self.bearings:
            if b.pos == pos:
                return b
        return None

    def _trace(self, b: Bearing) -> None:
        s = self.s
        if b.step is None:
            return
        start = (b.pos[0] + b.step[0], b.pos[1] + b.step[1], b.pos[2] + b.step[2])
        b.start = start
        if s.is_air(start):
            b.rotor, b.sails, b.contacts, b.reliable = set(), 0, [], True
            return
        seen = {start}
        queue = deque([start])
        contacts: list[dict] = []
        while queue and len(seen) < self.LIMIT:
            cur = queue.popleft()
            for d in SIX:
                nb = (cur[0] + d[0], cur[1] + d[1], cur[2] + d[2])
                if nb in seen or nb == b.pos or s.is_air(nb) or not s.inside(nb):
                    continue
                blk = s.blocks[nb]
                if is_brittle(blk["name"], blk["props"]):
                    if not attached_towards(blk["name"], blk["props"],
                                            OPPOSITE_DIR[d]):
                        continue
                if not b.in_front(nb):
                    if len(contacts) < 8:
                        contacts.append({"depuis": list(cur), "vers": list(nb),
                                         "bloc": blk["name"]})
                    continue
                seen.add(nb)
                queue.append(nb)
        is_sail = self.props.is_sail
        b.rotor = seen
        b.sails = sum(1 for p in seen if is_sail(s.name(p)))
        b.contacts = contacts
        b.reliable = not contacts and (b.sails == 0 or len(seen) < b.sails * 3 + 10)
