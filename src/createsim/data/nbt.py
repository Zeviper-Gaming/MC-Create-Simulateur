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


def retag(value, template=None):
    """Reconvertit un objet Python nu en balise nbtlib, guide par l'original.

    Le NBT des blocs est aplati au chargement (`simplify`), et le bandeau y
    ecrit (la molette d'un bruleur). Pour exporter, il faut donc retrouver les
    types : `Speed` est un Float, `NeedsSpeedUpdate` un Byte, `ScrollValue`
    un Int. Le tag d'origine sert de gabarit ; une cle nouvelle, sans gabarit,
    prend le type le plus courant du format (Int, Float, String).
    """
    if isinstance(template, T.Compound) or (template is None and isinstance(value, dict)):
        base = template if isinstance(template, T.Compound) else {}
        return T.Compound({str(k): retag(v, base.get(k)) for k, v in value.items()})
    if isinstance(template, (T.ByteArray, T.IntArray, T.LongArray)):
        return type(template)(list(value))
    if isinstance(template, T.List) or (template is None and isinstance(value, list)):
        items = list(value)
        sample = template[0] if isinstance(template, T.List) and len(template) else None
        tagged = [retag(x, sample) for x in items]
        if isinstance(template, T.List) and not tagged:
            return template.__class__([])
        subtype = type(tagged[0]) if tagged else T.End
        return T.List[subtype](tagged)
    if template is not None and not isinstance(template, (T.Compound, T.List)):
        if isinstance(template, T.String):
            return T.String(str(value))
        return type(template)(value)
    if isinstance(value, bool):
        return T.Byte(int(value))
    if isinstance(value, int):
        return T.Int(value)
    if isinstance(value, float):
        return T.Float(value)
    return T.String(str(value))


FACING_AXIS = {"east": "x", "west": "x", "up": "y", "down": "y",
               "north": "z", "south": "z"}

# Create DirectionalAxisKineticBlock : l'axe de rotation est perpendiculaire a
# `facing`, et `axis_along_first` choisit lequel des deux. C'est le cas des
# jauges (compte-tours, manometre) et des boitiers orientes : leur `facing`
# designe la face d'affichage, pas l'axe.
PERPENDICULAR = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}


def axis_of(block: dict) -> str | None:
    """Axe de rotation d'un bloc cinetique, d'apres son etat."""
    props = block.get("props") or {}
    ax = props.get("axis")
    if ax:
        return ax
    facing = props.get("facing")
    face_axis = FACING_AXIS.get(facing)
    if face_axis is None:
        return None
    if "axis_along_first" in props:
        first, second = PERPENDICULAR[face_axis]
        return first if props["axis_along_first"] == "true" else second
    return face_axis


class StructureError(ValueError):
    """Un fichier qui n'est pas une structure Minecraft lisible.

    Charger un `.nbt` depuis une fenetre, c'est aussi en charger un qui n'en est
    pas un : un `level.dat`, le cache d'une forteresse, un fichier tronque.
    Sans cette exception, l'utilisateur lisait `KeyError: 99` ou
    `KeyError: 'size'` — vrais, et inutilisables.
    """


#: les champs qui font d'un NBT une STRUCTURE (format des structure blocks)
REQUIRED_FIELDS = ("size", "DataVersion", "palette", "blocks")


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
        #: tout ce que le simulateur ne modelise pas, TYPE, pour l'export :
        #: colle, entites de contraption, `sub_levels` de Sable, cles futures.
        #: Un export qui les perdrait casserait le vaisseau une fois reimporte.
        self.passthrough: dict = {}
        self.gzipped = True
        self.byteorder = "big"
        self.root_name = ""
        if path is not None:
            self._load(path)

    # -- chargement --------------------------------------------------------
    def _load(self, path: str) -> None:
        name = str(path).replace("\\", "/").split("/")[-1]
        try:
            f = nbtlib.load(path)
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise StructureError(
                "%s n'est pas un fichier NBT lisible (%s : %s)"
                % (name, type(exc).__name__, exc)) from exc

        missing = [k for k in REQUIRED_FIELDS if k not in f]
        if missing:
            raise StructureError(
                "%s est un fichier NBT, mais pas une structure : il manque %s. "
                "Il faut un .nbt enregistre par un bloc de structure ou par "
                "l'outil de schematics de Create."
                % (name, ", ".join("« %s »" % k for k in missing)))
        try:
            self._parse(f)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise StructureError(
                "%s est une structure mal formee (%s : %s)"
                % (name, type(exc).__name__, exc)) from exc

    def _parse(self, f) -> None:
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
                # le tag d'origine, TYPE : un bloc de structure en jeu lit une
                # valeur au mauvais type comme zero, sans erreur
                entry["tag"] = b["nbt"]
            self.blocks[pos] = entry
            self.by_name.setdefault(entry["name"], set()).add(pos)
        self.entities = [simplify(e) for e in f.get("entities", [])]
        self.passthrough = {str(k): v for k, v in f.items()
                            if str(k) not in ("size", "palette", "blocks")}
        self.gzipped = bool(getattr(f, "gzipped", True))
        self.byteorder = getattr(f, "byteorder", "big")
        self.root_name = str(getattr(f, "root_name", "") or "")

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

    # -- export (F6.7) -----------------------------------------------------
    def to_nbt(self) -> "nbtlib.File":
        """La structure courante, au format des blocs de structure.

        Seuls `size`, `palette` et `blocks` sont reconstruits. Tout le reste de
        la racine — colle, entites, `sub_levels` — repart tel qu'il a ete lu.
        """
        palette: dict[tuple, int] = {}
        palette_tags: list = []
        blocks: list = []
        for pos in sorted(self.blocks):
            entry = self.blocks[pos]
            key = (entry["name"], tuple(sorted((entry.get("props") or {}).items())))
            index = palette.get(key)
            if index is None:
                index = palette[key] = len(palette_tags)
                state = {"Name": T.String(entry["name"])}
                if key[1]:
                    state["Properties"] = T.Compound(
                        {k: T.String(v) for k, v in key[1]})
                palette_tags.append(T.Compound(state))
            block = {"pos": T.List[T.Int]([T.Int(v) for v in pos]),
                     "state": T.Int(index)}
            if "nbt" in entry:
                block["nbt"] = retag(entry["nbt"], entry.get("tag"))
            blocks.append(T.Compound(block))

        root = dict(self.passthrough)
        root["size"] = T.List[T.Int]([T.Int(v) for v in self.size])
        root["palette"] = T.List[T.Compound](palette_tags)
        root["blocks"] = T.List[T.Compound](blocks)
        if "DataVersion" not in root:
            root["DataVersion"] = T.Int(self.data_version)
        return nbtlib.File(root, gzipped=self.gzipped, byteorder=self.byteorder)

    def export(self, path: str) -> str:
        """Ecrit la variante dans un fichier NOUVEAU (F6.7).

        Deux refus, et ce sont les garde-fous du cahier : jamais le fichier
        source, jamais un fichier existant. Une variante qui ecraserait quoi
        que ce soit ne serait plus non destructive.
        """
        import os
        target = os.path.abspath(str(path))
        if self.path and os.path.abspath(str(self.path)) == target:
            raise PermissionError("le fichier source n'est jamais ecrit : %s" % path)
        if os.path.exists(target):
            raise FileExistsError("l'export ne remplace aucun fichier : %s" % path)
        self.to_nbt().save(target)
        return target

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
