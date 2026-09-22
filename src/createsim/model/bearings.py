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

from ..data.nbt import AIR_NAMES, Pos, SIX
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
                 "contacts", "reliable", "assembled", "last_generated",
                 "handedness")

    def __init__(self, pos: Pos, name: str, facing: str | None,
                 assembled: bool = False, last_generated: float = 0.0,
                 handedness: int = 1):
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
        #: +1 ou -1 : l'option a la molette du palier d'helice (`ScrollValue`,
        #: enum ThrustDirection RIGHT_HANDED / LEFT_HANDED). C'est ELLE qui
        #: renverse la poussee, pas le sens du bloc.
        self.handedness = handedness

    @property
    def sails_known(self) -> bool:
        return not self.assembled

    @property
    def thrust_axis(self) -> tuple[float, float, float] | None:
        """L'axe POSITIF du palier — la direction ou sa poussee s'exerce.

        `PropellerBearingBlockEntity.getDirectionIndependentSpeed()` multiplie
        le vecteur `facing` par `FACING.getAxisDirection().getStep()`. Le
        produit vaut toujours l'unite positive de l'axe : un palier tourne vers
        le nord et un tourne vers le sud poussent dans le MEME sens. On inverse
        par le regime ou par la molette, jamais en retournant le bloc.
        """
        if self.step is None:
            return None
        return tuple(abs(c) for c in self.step)

    def in_front(self, q: Pos) -> bool:
        if self.step is None or self.start is None:
            return False
        s, st = self.start, self.step
        return sum((q[i] - s[i]) * st[i] for i in range(3)) >= 0

    def report(self) -> dict:
        out = {
            "pos": list(self.pos), "bloc": self.name, "orientation": self.facing,
            "sens_de_poussee": ("axe %s positif%s"
                                % ("xyz"[self.step.index(max(self.step,
                                                             key=abs))],
                                   "" if self.handedness > 0 else ", molette inversee")
                                if self.step else None),
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

    @staticmethod
    def _touches(b: "Bearing", pos: Pos) -> bool:
        """Une edition en `pos` peut-elle changer le rotor de ce palier ?

        Le rotor est la composante CONNEXE partie du bloc de depart : un bloc
        ne peut le rejoindre ou le quitter que s'il en fait partie ou s'il lui
        est contigu. Le test du demi-espace avant, plus large, faisait retracer
        les dix paliers du c1_air_cruiser pour 72 % des editions — 106 ms.
        Les contacts avec la coque sont contigus au rotor : ils restent vus.
        """
        if pos == b.pos or pos == b.start or pos in b.rotor:
            return True
        return any((pos[0] + d[0], pos[1] + d[1], pos[2] + d[2]) in b.rotor
                   for d in SIX)

    def affected_by(self, pos: Pos) -> bool:
        if any(self._touches(b, pos) for b in self.bearings):
            return True
        # un palier pose la ou il n'y en avait pas
        return self.s.name(pos) in BEARINGS

    def digest(self):
        """Ce que lisent les dependants : le reseau cinetique prend le NOMBRE
        de voiles d'un moulin et l'etat assemble ; l'organe des voiles ecarte
        les voiles des rotors, et une voile qui entre ou sort d'un rotor en
        change le compte. Le resume couvre donc les deux."""
        return tuple((b.pos, b.sails, b.assembled) for b in self.bearings)

    def apply_delta(self, edits) -> bool:
        """Ne retrace que les paliers touches — « le rotor D'UN palier ».

        Poser ou retirer un palier change la liste elle-meme : on refait tout.
        """
        for e in edits:
            for entry in (e.before, e.after):
                if entry and entry["name"] in BEARINGS:
                    return False
        for b in self.bearings:
            if not b.assembled and any(self._touches(b, e.pos) for e in edits):
                self._trace(b)
        return True

    def recompute(self) -> None:
        self.bearings = []
        for name in BEARINGS:
            for pos in sorted(self.s.positions_of(name)):
                block = self.s.blocks[pos]
                nbt = block.get("nbt") or {}
                b = Bearing(pos, name, block["props"].get("facing"),
                            assembled=bool(nbt.get("Running")),
                            last_generated=float(nbt.get("LastGenerated") or 0.0),
                            handedness=-1 if int(nbt.get("ScrollValue") or 0) == 1
                            else 1)
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
        """Le rotor : la composante connexe partie du bloc devant le palier.

        Boucle resserree — c'est le poste le plus lourd d'une edition sur un
        vaisseau aux rotors soudes a la coque (6 000 blocs par trace). Bornes,
        air et demi-espace sont testes en ligne plutot que par appels.
        """
        s = self.s
        if b.step is None:
            return
        start = (b.pos[0] + b.step[0], b.pos[1] + b.step[1], b.pos[2] + b.step[2])
        b.start = start
        if s.is_air(start):
            b.rotor, b.sails, b.contacts, b.reliable = set(), 0, [], True
            return
        blocks = s.blocks
        sx, sy, sz = s.size
        ox, oy, oz = start
        kx, ky, kz = b.step
        bpos = b.pos
        limit = self.LIMIT
        seen = {start}
        queue = deque([start])
        contacts: list[dict] = []
        while queue and len(seen) < limit:
            cur = queue.popleft()
            cx, cy, cz = cur
            for d in SIX:
                nx, ny, nz = cx + d[0], cy + d[1], cz + d[2]
                if not (0 <= nx < sx and 0 <= ny < sy and 0 <= nz < sz):
                    continue
                nb = (nx, ny, nz)
                if nb in seen or nb == bpos:
                    continue
                blk = blocks.get(nb)
                if blk is None:
                    continue
                name = blk["name"]
                if name in AIR_NAMES:
                    continue
                props = blk["props"]
                if is_brittle(name, props):
                    if not attached_towards(name, props, OPPOSITE_DIR[d]):
                        continue
                if (nx - ox) * kx + (ny - oy) * ky + (nz - oz) * kz < 0:
                    if len(contacts) < 8:
                        contacts.append({"depuis": list(cur), "vers": list(nb),
                                         "bloc": name})
                    continue
                seen.add(nb)
                queue.append(nb)
        sails = self.tables.cached_set("masses.sail_blocks")
        b.rotor = seen
        b.sails = sum(1 for p in seen if blocks[p]["name"] in sails)
        b.contacts = contacts
        b.reliable = not contacts and (b.sails == 0 or len(seen) < b.sails * 3 + 10)
