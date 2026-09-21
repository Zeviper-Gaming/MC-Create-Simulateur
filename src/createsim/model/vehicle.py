"""Le vehicule : un jeu d'organes, et l'invalidation selective qui les relie.

C'est le point dur du cahier, et le seul qui engage l'architecture. Une edition
n'est pas couteuse en elle-meme ; ce qui coute, c'est ce qu'elle invalide. Les
organes n'ont pas le meme prix de recalcul, et le simulateur ne doit refaire que
ce que le bloc touche concerne reellement.

Cette architecture se concoit au depart : la greffer sur un modele calcule d'un
seul bloc au chargement reviendrait a le reecrire.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..data.names import Names
from ..data.nbt import Pos, Structure
from ..data.tables import BlockProperties, Tables


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
    work: Counter = field(default_factory=Counter, init=False)

    def __post_init__(self) -> None:
        self.props = BlockProperties(self.tables)

    # -- construction ------------------------------------------------------
    @classmethod
    def load(cls, path: str, tables: Tables | None = None) -> "VehicleModel":
        from .balloons import BalloonOrgan
        from .bearings import BearingOrgan
        from .drag import DragOrgan
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
        for cls_ in (MassOrgan, DragOrgan, LevititeOrgan, RedstoneOrgan,
                     WheelOrgan, BearingOrgan, SailOrgan, KineticOrgan,
                     StressOrgan, BalloonOrgan):
            organ = cls_(model)
            model.organs[organ.name] = organ
            model.order.append(organ.name)
        model.rebuild()
        return model

    def rebuild(self) -> None:
        for name in self.order:
            self.organs[name]._run(None)

    def organ(self, name: str) -> Organ:
        return self.organs[name]

    # -- edition (niveau 2) ------------------------------------------------
    def apply_edits(self, edits: list[Edit], record: bool = True) -> dict[str, str]:
        """Applique des editions deja faites sur la structure et n'invalide que
        les organes reellement concernes. Renvoie organe -> mode de recalcul."""
        dirty: set[str] = set()
        for name in self.order:
            organ = self.organs[name]
            if any(organ.affected_by(e.pos) for e in edits):
                dirty.add(name)

        # propagation des dependances entre organes
        changed = True
        while changed:
            changed = False
            for name in self.order:
                if name in dirty:
                    continue
                if any(dep in dirty for dep in self.organs[name].depends):
                    dirty.add(name)
                    changed = True

        done: dict[str, str] = {}
        for name in self.order:
            if name in dirty:
                done[name] = self.organs[name]._run(edits)
                self.work[name] += 1
        if record:
            self.edits.append(edits)
            self.redone.clear()
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
        return self.apply_edits([Edit(pos, before, after)])

    def move(self, src: Pos, dst: Pos) -> dict[str, str]:
        """Deplace un bloc. Refuse d'ecraser un bloc existant (F6.3)."""
        if dst in self.structure.blocks:
            raise ValueError("superposition refusee : %s est occupe" % (dst,))
        if not self.structure.inside(dst):
            raise ValueError("hors de la structure : %s" % (dst,))
        entry = self.structure.blocks.get(src)
        if entry is None:
            raise ValueError("aucun bloc a deplacer en %s" % (src,))
        entry = dict(entry)
        self.structure.remove_block(src)
        self.structure.set_block(dst, entry["name"], entry.get("props"),
                                 entry.get("nbt"))
        return self.apply_edits([Edit(src, entry, None),
                                 Edit(dst, None, dict(self.structure.blocks[dst]))])

    # -- pile d'annulation -------------------------------------------------
    def undo(self) -> bool:
        if not self.edits:
            return False
        batch = self.edits.pop()
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
        for e in batch:
            self.structure.restore_block(e.pos, e.after)
        self.apply_edits(batch, record=False)
        self.edits.append(batch)
        return True

    def revert(self) -> int:
        """Retour a l'original en une commande (F6.5)."""
        n = 0
        while self.undo():
            n += 1
        self.redone.clear()
        return n

    @property
    def edited(self) -> bool:
        return bool(self.edits)
