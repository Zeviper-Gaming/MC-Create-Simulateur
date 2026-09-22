"""Le vehicule : un jeu d'organes, et l'invalidation selective qui les relie.

C'est le point dur du cahier, et le seul qui engage l'architecture. Une edition
n'est pas couteuse en elle-meme ; ce qui coute, c'est ce qu'elle invalide. Les
organes n'ont pas le meme prix de recalcul, et le simulateur ne doit refaire que
ce que le bloc touche concerne reellement.

Cette architecture se concoit au depart : la greffer sur un modele calcule d'un
seul bloc au chargement reviendrait a le reecrire.
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field

from ..data.names import Names
from ..data.nbt import Pos, Structure
from ..data.tables import BlockProperties, Tables


HORIZONTAL_FACINGS = ("north", "south", "east", "west")
FACING_ORDER = ("north", "south", "east", "west", "up", "down", "x", "y", "z",
                "false", "true")
AIR = frozenset(("minecraft:air", "minecraft:cave_air", "minecraft:void_air"))


def _palette_of(structure: Structure) -> dict[str, dict]:
    """Un gabarit par type de bloc, pris sur le premier bloc de ce type.

    Copie profonde : poser un bloc ne doit jamais partager son NBT avec celui
    dont il est le clone, sinon regler la molette de l'un reglerait l'autre.
    """
    palette: dict[str, dict] = {}
    for name in sorted(structure.names()):
        if name in AIR:
            continue
        positions = structure.positions_of(name)
        if positions:
            palette[name] = copy.deepcopy(structure.blocks[min(positions)])
    return palette


@dataclass
class Edit:
    """Une edition elementaire, telle que la pile d'annulation la retient."""

    pos: Pos
    before: dict | None
    after: dict | None


class Organ:
    """Un organe du modele : une grandeur derivee de la structure.

    Trois choses le definissent — son cout, ce qui le rend sale, et comment il
    se refait. Le reste du simulateur ne le connait que par ces trois-la.
    """

    name: str = "organe"
    cost: str = "faible"
    depends: tuple[str, ...] = ()

    def __init__(self, model: "VehicleModel"):
        self.model = model
        self.recomputes = 0

    # -- a implementer -----------------------------------------------------
    def affected_by(self, pos: Pos) -> bool:
        """Vrai si une edition en `pos` invalide cet organe. Doit etre O(1)."""
        raise NotImplementedError

    def recompute(self) -> None:
        """Refait l'organe entierement."""
        raise NotImplementedError

    def apply_delta(self, edits: list[Edit]) -> bool:
        """Mise a jour incrementale. Renvoie False pour exiger un recalcul complet."""
        return False

    # -- service -----------------------------------------------------------
    @property
    def s(self) -> Structure:
        return self.model.structure

    @property
    def props(self) -> BlockProperties:
        return self.model.props

    @property
    def tables(self) -> Tables:
        return self.model.tables

    def digest(self):
        """Ce que les organes DEPENDANTS lisent de celui-ci, en resume.

        Si le resume ne change pas, les dependants n'ont rien a refaire. `None`
        (le defaut) veut dire « inconnu » : la propagation reste alors
        systematique, comme avant. Un resume trop pauvre laisserait un
        dependant perime — il doit couvrir TOUT ce que les dependants lisent.
        """
        return None

    def _run(self, edits: list[Edit] | None) -> str:
        """Choisit entre delta et recalcul complet, et compte le vrai cout."""
        if edits and self.apply_delta(edits):
            return "delta"
        self.recompute()
        self.recomputes += 1
        return "complet"


@dataclass
class VehicleModel:
    """Ce que la structure contient.

    Ne bouge que lorsque l'utilisateur edite un bloc ; l'etat, lui, change a
    chaque tick. Remettre a zero, c'est jeter l'etat et garder ce modele.
    """

    structure: Structure
    tables: Tables
    names: Names = field(default_factory=Names)
    props: BlockProperties = field(init=False)
    organs: dict[str, Organ] = field(default_factory=dict, init=False)
    order: list[str] = field(default_factory=list, init=False)
    edits: list[list[Edit]] = field(default_factory=list, init=False)
    redone: list[list[Edit]] = field(default_factory=list, init=False)
    #: les INTENTIONS, en lockstep avec `edits` : « supprimer 12,4,7 » plutot
    #: que deux etats de bloc. C'est ce qu'un scenario enregistre et rejoue.
    ops: list[dict] = field(default_factory=list, init=False)
    redone_ops: list[dict] = field(default_factory=list, init=False)
    #: la palette d'ajout : les types presents AU CHARGEMENT, un gabarit chacun.
    #: Figee a ce moment-la, pour que supprimer le dernier bloc d'un type ne le
    #: retire pas de ce qu'on peut reposer.
    palette: dict[str, dict] = field(default_factory=dict, init=False)
    work: Counter = field(default_factory=Counter, init=False)

    def __post_init__(self) -> None:
        self.props = BlockProperties(self.tables)

    # -- construction ------------------------------------------------------
    @classmethod
    def load(cls, path: str, tables: Tables | None = None) -> "VehicleModel":
        from .balloons import BalloonOrgan
        from .bearings import BearingOrgan
        from .drag import DragOrgan
        from .hull import HullOrgan
        from .kinetics import KineticOrgan
        from .levitite import LevititeOrgan
        from .mass import MassOrgan
        from .redstone import RedstoneOrgan
        from .sails import SailOrgan
        from .stress import StressOrgan
        from .wheels import WheelOrgan

        structure = Structure(path)
        model = cls(structure, tables or Tables.load(),
                    Names.for_structure(path))
        # L'ordre est celui des dependances : les voiles d'un palier alimentent
        # le regime d'un moulin, donc les paliers passent avant la cinetique.
        for cls_ in (MassOrgan, DragOrgan, HullOrgan, LevititeOrgan,
                     RedstoneOrgan, WheelOrgan, BearingOrgan, SailOrgan,
                     KineticOrgan, StressOrgan, BalloonOrgan):
            organ = cls_(model)
            model.organs[organ.name] = organ
            model.order.append(organ.name)
        model.palette = _palette_of(structure)
        model.rebuild()
        return model

    def rebuild(self) -> None:
        for name in self.order:
            self.organs[name]._run(None)

    def organ(self, name: str) -> Organ:
        return self.organs[name]

    # -- edition (niveau 2) ------------------------------------------------
    def apply_edits(self, edits: list[Edit], record: bool = True,
                    op: dict | None = None) -> dict[str, str]:
        """Applique des editions deja faites sur la structure et n'invalide que
        les organes reellement concernes. Renvoie organe -> mode de recalcul."""
        direct = {name for name in self.order
                  if any(self.organs[name].affected_by(e.pos) for e in edits)}

        # Dans l'ordre des dependances : un organe tourne s'il est touche, ou si
        # ce qu'il lit d'un organe dont il depend a CHANGE. Retirer un bloc de
        # coque d'un rotor soude change le rotor, rarement son nombre de voiles
        # — et le reseau cinetique, qui ne lit que ce nombre, n'a rien a
        # refaire. Sur le c1_air_cruiser, c'etait 13 ms par edition pour rien.
        done: dict[str, str] = {}
        changed: set[str] = set()
        for name in self.order:
            organ = self.organs[name]
            if name not in direct and not any(d in changed for d in organ.depends):
                continue
            before = organ.digest()
            done[name] = organ._run(edits)
            self.work[name] += 1
            after = organ.digest()
            if before is None or after is None or before != after:
                changed.add(name)
        if record:
            self.edits.append(edits)
            self.ops.append(op or {"op": "brut", "pos": [list(e.pos) for e in edits]})
            self.redone.clear()
            self.redone_ops.clear()
        return done

    def edit(self, pos: Pos, name: str | None, props: dict | None = None,
             nbt: dict | None = None) -> dict[str, str]:
        """Pose (`name`) ou supprime (`name=None`) un bloc, puis invalide."""
        before = self.structure.blocks.get(pos)
        before = dict(before) if before else None
        if name is None:
            self.structure.remove_block(pos)
        else:
            self.structure.set_block(pos, name, props, nbt)
        after = self.structure.blocks.get(pos)
        after = dict(after) if after else None
        op = ({"op": "supprimer", "pos": list(pos)} if name is None else
              {"op": "poser", "pos": list(pos), "bloc": name,
               "props": dict(props or {})})
        return self.apply_edits([Edit(pos, before, after)], op=op)

    # -- les quatre gestes du cahier (F6.2) --------------------------------
    def _check_free(self, pos: Pos) -> None:
        """Grille entiere, un bloc par case (F6.3)."""
        if not self.structure.inside(pos):
            raise ValueError("hors de la structure : %s" % (pos,))
        if pos in self.structure.blocks and not self.structure.is_air(pos):
            raise ValueError("superposition refusee : %s est occupe" % (pos,))

    def delete(self, pos: Pos) -> dict[str, str]:
        """« Ce lest sert-il a quelque chose ? »"""
        pos = tuple(pos)
        if pos not in self.structure.blocks:
            raise ValueError("aucun bloc en %s" % (pos,))
        return self.edit(pos, None)

    def add(self, pos: Pos, name: str, props: dict | None = None) -> dict[str, str]:
        """« Un bruleur de plus a l'arriere ? »

        Palette restreinte aux types deja presents dans le fichier charge : le
        bloc pose est un clone d'un bloc existant de ce type, NBT compris. C'est
        ce qui garantit qu'il s'exporte avec des donnees que le jeu sait lire.
        """
        pos = tuple(pos)
        if name not in self.palette:
            raise ValueError("%s n'est pas dans la palette de ce vaisseau" % name)
        self._check_free(pos)
        entry = copy.deepcopy(self.palette[name])
        if props:
            entry["props"] = {**entry.get("props", {}), **dict(props)}
        self.structure.restore_block(pos, entry)
        return self.apply_edits(
            [Edit(pos, None, dict(entry))],
            op={"op": "poser", "pos": list(pos), "bloc": name,
                "props": dict(entry.get("props") or {})})

    def set_property(self, pos: Pos, key: str, value: str) -> dict[str, str]:
        """« Et si je retourne ce palier ? »"""
        pos = tuple(pos)
        entry = self.structure.blocks.get(pos)
        if entry is None:
            raise ValueError("aucun bloc en %s" % (pos,))
        before = dict(entry)
        after = dict(entry)
        after["props"] = {**entry.get("props", {}), str(key): str(value)}
        self.structure.restore_block(pos, after)
        return self.apply_edits(
            [Edit(pos, before, dict(after))],
            op={"op": "propriete", "pos": list(pos), "cle": str(key),
                "valeur": str(value)})

    def move(self, src: Pos, dst: Pos) -> dict[str, str]:
        """« Et si ce palier d'helice etait trois blocs plus haut ? »

        Le bloc voyage ENTIER : etat, NBT et tag type. Le reconstruire a partir
        de son nom perdait les types, et l'export aurait ecrit des zeros.
        """
        src, dst = tuple(src), tuple(dst)
        entry = self.structure.blocks.get(src)
        if entry is None:
            raise ValueError("aucun bloc a deplacer en %s" % (src,))
        self._check_free(dst)
        entry = dict(entry)
        self.structure.remove_block(src)
        self.structure.restore_block(dst, entry)
        return self.apply_edits(
            [Edit(src, entry, None), Edit(dst, None, dict(entry))],
            op={"op": "deplacer", "de": list(src), "vers": list(dst)})

    def property_choices(self, name: str, key: str) -> list[str]:
        """Les valeurs qu'on propose pour une propriete, sans registre de blocs.

        Le simulateur ne connait pas les etats valides de chaque bloc : il
        propose ceux vus dans le fichier pour ce type, elargis aux enumerations
        sures (`axis`, booleens, `facing` a 4 ou 6 directions selon ce que le
        fichier montre deja). Une variante qui va bien a l'ecran ne tient pas
        forcement en jeu : c'est la reserve du cahier.
        """
        seen = {self.structure.blocks[pos]["props"][key]
                for pos in self.structure.positions_of(name)
                if key in self.structure.blocks[pos].get("props", {})}
        template = self.palette.get(name, {}).get("props", {})
        if key in template:
            seen.add(template[key])
        if key == "axis":
            seen |= {"x", "y", "z"}
        elif key == "facing":
            seen |= set(HORIZONTAL_FACINGS)
            if seen & {"up", "down"}:
                seen |= {"up", "down"}
        elif seen and seen <= {"true", "false"}:
            seen |= {"true", "false"}
        order = {v: i for i, v in enumerate(FACING_ORDER)}
        return sorted(seen, key=lambda v: (order.get(v, 99), v))

    # -- pile d'annulation -------------------------------------------------
    def undo(self) -> bool:
        if not self.edits:
            return False
        batch = self.edits.pop()
        if self.ops:
            self.redone_ops.append(self.ops.pop())
        for e in reversed(batch):
            self.structure.restore_block(e.pos, e.before)
        self.apply_edits([Edit(e.pos, e.after, e.before) for e in batch],
                         record=False)
        self.redone.append(batch)
        return True

    def redo(self) -> bool:
        if not self.redone:
            return False
        batch = self.redone.pop()
        if self.redone_ops:
            self.ops.append(self.redone_ops.pop())
        for e in batch:
            self.structure.restore_block(e.pos, e.after)
        self.apply_edits(batch, record=False)
        self.edits.append(batch)
        return True

    def revert(self) -> int:
        """Retour a l'original en une commande (F6.5), et en UNE passe.

        Rejouer les annulations une a une recalculait les organes a chaque
        fois : 1,6 s pour trente editions. On remet tous les blocs d'abord,
        puis on invalide une seule fois ce que l'ensemble a touche.
        """
        n = len(self.edits)
        if not n:
            return 0
        undone: list[Edit] = []
        for batch in reversed(self.edits):
            for e in reversed(batch):
                self.structure.restore_block(e.pos, e.before)
                undone.append(Edit(e.pos, e.after, e.before))
        self.edits.clear()
        self.ops.clear()
        self.redone.clear()
        self.redone_ops.clear()
        self.apply_edits(undone, record=False)
        return n

    @property
    def edited(self) -> bool:
        return bool(self.edits)
