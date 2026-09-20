"""Lecture d'une structure Minecraft (.nbt) et modele de blocs mutable.

Le fichier d'origine n'est JAMAIS ecrit. Les editions vivent en memoire, au
dessus du modele charge ; l'export d'une variante passe par un fichier nouveau.

Deux ajouts par rapport au lecteur du calculateur statique :
  - un index nom -> positions, pour que `of_type` ne balaie pas les 20 000
    blocs a chaque appel ;
  - des mutateurs qui emettent un evenement d'edition, socle de l'invalidation
    par organe.
"""
from __future__ import annotations

from typing import Callable, Iterable, Iterator

import nbtlib
import nbtlib.tag as T

Pos = tuple[int, int, int]

HORIZONTAL: tuple[Pos, ...] = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))
SIX: tuple[Pos, ...] = HORIZONTAL + ((0, 1, 0), (0, -1, 0))
AIR_NAMES = frozenset(("minecraft:air", "minecraft:cave_air", "minecraft:void_air"))


def simplify(v):
    """Convertit recursivement une balise nbtlib en objet Python nu."""
    if isinstance(v, T.Compound):
        return {str(k): simplify(x) for k, x in v.items()}
    if isinstance(v, T.List):
        return [simplify(x) for x in v]
    if isinstance(v, (T.ByteArray, T.IntArray, T.LongArray)):
        return [int(x) for x in v]
    if isinstance(v, T.String):
        return str(v)
    if isinstance(v, (T.Byte, T.Short, T.Int, T.Long)):
        return int(v)
    if isinstance(v, (T.Float, T.Double)):
        return float(v)
    return str(v)


def axis_of(block: dict) -> str | None:
    """Axe de rotation d'un bloc cinetique, d'apres son etat."""
    props = block.get("props") or {}
    ax = props.get("axis")
    if ax:
        return ax
    facing = props.get("facing")
    if facing in ("east", "west"):
        return "x"
    if facing in ("up", "down"):
        return "y"
    if facing in ("north", "south"):
        return "z"
    return None


class Structure:
    """La carte 3D des blocs, avec etat et NBT de chaque block entity (F1.2)."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.size: Pos = (0, 0, 0)
        self.data_version = 0
        self.blocks: dict[Pos, dict] = {}
        self.entities: list = []
        self.by_name: dict[str, set[Pos]] = {}
        self.revision = 0
        if path is not None:
            self._load(path)

    # -- chargement --------------------------------------------------------
    def _load(self, path: str) -> None:
        f = nbtlib.load(path)
        self.size = tuple(int(x) for x in f["size"])
        self.data_version = int(f["DataVersion"])
        palette = f["palette"]
        for b in f["blocks"]:
            pos = tuple(int(x) for x in b["pos"])
            st = palette[int(b["state"])]
            props = ({str(k): str(v) for k, v in dict(st["Properties"]).items()}
                     if "Properties" in st else {})
            entry = {"name": str(st["Name"]), "props": props}
            if "nbt" in b:
                entry["nbt"] = simplify(b["nbt"])
            self.blocks[pos] = entry
            self.by_name.setdefault(entry["name"], set()).add(pos)
        self.entities = [simplify(e) for e in f["entities"]]

    # -- consultation ------------------------------------------------------
    def name(self, pos: Pos) -> str:
        b = self.blocks.get(pos)
        return b["name"] if b else "minecraft:air"

    def inside(self, pos: Pos) -> bool:
        return all(0 <= pos[i] < self.size[i] for i in range(3))

    def is_air(self, pos: Pos) -> bool:
        b = self.blocks.get(pos)
        return b is None or b["name"] in AIR_NAMES

    def of_type(self, name: str) -> dict[Pos, dict]:
        return {p: self.blocks[p] for p in self.by_name.get(name, ())}

    def positions_of(self, name: str) -> set[Pos]:
        return self.by_name.get(name, set())

    def matching(self, pred: Callable[[str], bool]) -> dict[Pos, dict]:
        """Blocs dont le nom satisfait le predicat, via l'index de noms."""
        out: dict[Pos, dict] = {}
        for name, positions in self.by_name.items():
            if pred(name):
                for p in positions:
                    out[p] = self.blocks[p]
        return out

    def count_matching(self, pred: Callable[[str], bool]) -> int:
        return sum(len(ps) for n, ps in self.by_name.items() if pred(n))

    def names(self) -> Iterable[str]:
        return self.by_name.keys()

    def __len__(self) -> int:
        return len(self.blocks)

    def __iter__(self) -> Iterator[tuple[Pos, dict]]:
        return iter(self.blocks.items())

    def neighbours(self, pos: Pos) -> Iterator[tuple[Pos, dict]]:
        for d in SIX:
            q = (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])
            b = self.blocks.get(q)
            if b is not None:
                yield q, b

    # -- edition (niveau 2) ------------------------------------------------
    def set_block(self, pos: Pos, name: str, props: dict | None = None,
                  nbt: dict | None = None) -> dict | None:
        """Pose un bloc. Renvoie ce qui s'y trouvait, pour la pile d'annulation."""
        previous = self.remove_block(pos)
        entry = {"name": name, "props": dict(props or {})}
        if nbt:
            entry["nbt"] = nbt
        self.blocks[pos] = entry
        self.by_name.setdefault(name, set()).add(pos)
        self.revision += 1
        return previous

    def remove_block(self, pos: Pos) -> dict | None:
        previous = self.blocks.pop(pos, None)
        if previous is not None:
            bucket = self.by_name.get(previous["name"])
            if bucket is not None:
                bucket.discard(pos)
                if not bucket:
                    del self.by_name[previous["name"]]
            self.revision += 1
        return previous

    def restore_block(self, pos: Pos, entry: dict | None) -> None:
        """Remet en place exactement ce que `set_block` / `remove_block` a rendu."""
        self.remove_block(pos)
        if entry is not None:
            self.blocks[pos] = entry
            self.by_name.setdefault(entry["name"], set()).add(pos)
            self.revision += 1
