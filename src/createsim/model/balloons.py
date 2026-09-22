"""Poches de ballon : geometrie par flood-fill, et les bruleurs qui les alimentent.

Cout eleve. Invalide seulement si le bloc touche est etanche, ou a l'interieur
ou au contact d'une poche. Deplacer un coffre dans la soute ne doit rien couter.

Le remplissage n'est relance que sur LA POCHE CONCERNEE, jamais sur le vaisseau
entier : c'est pour cela que chaque poche retient ses cellules et sa coquille de
contact, et que l'appartenance se teste en O(1).

Port de `upwardsBiasedFloodFill` + `completeBalloon` (Aeronautics
`BalloonBuilder`). Hors des limites de la structure, l'espace est considere
ouvert sur le monde : la propagation y est declaree non sure (fuite), ce qui
borne le ballon exactement comme le fait la hauteur de construction en jeu.
"""
from __future__ import annotations

from collections import deque

from ..data.nbt import HORIZONTAL, Pos, SIX, Structure
from ..data.tables import BlockProperties
from .vehicle import Edit, Organ

BURNER_BLOCKS = ("aeronautics:adjustable_burner", "aeronautics:steam_vent")
DEFAULT_SCROLL = {"aeronautics:adjustable_burner": None,   # tables: burner_max_hot_air
                  "aeronautics:steam_vent": 5000}


class BalloonFiller:
    """Le flood-fill d'Aeronautics, avec des tests d'appartenance en O(1).

    Le calculateur statique reconstruisait `graph | added | layer` a chaque bloc
    visite, ce qui rend le remplissage quadratique des qu'une poche grossit. Les
    unions sont ici remplacees par trois tests d'appartenance : meme resultat,
    cout lineaire.
    """

    def __init__(self, s: Structure, props: BlockProperties,
                 main: set[Pos] | None = None):
        self.s = s
        self.props = props
        self.main = main or set()
        #: les cases inondees par les tentatives REJETEES parce qu'elles
        #: s'echappaient de la structure. Le trou y figure : c'est par la que
        #: la tentative est sortie. Y remettre un bloc etanche peut refermer
        #: la poche — et c'est la seule facon de le savoir sans tout refaire.
        self.leaks: set[Pos] = set()

    def _blocked(self, pos: Pos) -> bool:
        return pos in self.main or self.props.is_airtight(self.s.name(pos))

    def upward_fill(self, start: Pos, graph: set[Pos], existing: set[Pos]):
        s = self.s
        if not s.inside(start):
            return False, set()
        if start in graph or start in existing or self._blocked(start):
            return False, set()

        added: set[Pos] = set()
        stack = [start]

        while stack:
            origin = stack.pop()
            if (origin in graph or origin in added or origin in existing
                    or self._blocked(origin)):
                continue

            visited = {origin}
            queue = deque([origin])
            layer: set[Pos] = set()

            while queue:
                cur = queue.pop()               # LIFO, comme le mod
                if not s.inside(cur):
                    self.leaks |= added | layer
                    return False, set()
                if (cur in graph or cur in added or cur in layer
                        or cur in existing or self._blocked(cur)):
                    continue
                layer.add(cur)

                above = (cur[0], cur[1] + 1, cur[2])
                if above not in visited and not (
                        above in graph or above in added or above in layer
                        or above in existing or self._blocked(above)):
                    if not s.inside(above):
                        self.leaks |= added | layer | {cur}
                        return False, set()
                    stack.append(above)

                for dx, dy, dz in HORIZONTAL:
                    nb = (cur[0] + dx, cur[1] + dy, cur[2] + dz)
                    if nb not in visited:
                        visited.add(nb)
                        queue.append(nb)

            added |= layer

        graph |= added
        return True, added

    def complete(self, graph: set[Pos]) -> set[Pos]:
        progress = True
        while progress:
            progress = False
            for pos in sorted(graph, key=lambda p: p[1]):
                below = (pos[0], pos[1] - 1, pos[2])
                if below in graph or not self.s.inside(below):
                    continue
                if self._blocked(below):
                    continue
                trial: set[Pos] = set()
                safe, added = self.upward_fill(below, trial, graph)
                if safe and added:
                    graph |= added
                    progress = True
        return graph

    def build(self, start: Pos) -> set[Pos] | None:
        graph: set[Pos] = set()
        safe, _ = self.upward_fill(start, graph, set())
        if not safe:
            return None
        return self.complete(graph)


class Pocket:
    """Une poche de gaz : son volume, son barycentre, et ses bruleurs."""

    __slots__ = ("cells", "air", "centre", "burners", "shell")

    def __init__(self, cells: set[Pos], air: list[Pos], centre, burners):
        self.cells = cells
        self.air = air
        self.centre = centre
        self.burners: list[dict] = burners
        self.shell: set[Pos] = set()

    @property
    def capacity(self) -> int:
        return len(self.air)

    def demand(self, signals: dict[Pos, int] | None = None) -> float:
        """Cible de gaz demandee par les bruleurs, au signal courant."""
        total = 0.0
        for b in self.burners:
            sig = b["signal"] if signals is None else signals.get(b["pos"], b["signal"])
            total += b["reglage"] * max(0, min(15, sig)) / 15.0
        return total

    @property
    def max_demand(self) -> float:
        return sum(b["reglage"] for b in self.burners)

    def build_shell(self) -> None:
        shell: set[Pos] = set()
        for p in self.cells:
            for d in SIX:
                q = (p[0] + d[0], p[1] + d[1], p[2] + d[2])
                if q not in self.cells:
                    shell.add(q)
        self.shell = shell

    def report(self, lift_strength: float, quantity: float | None = None) -> dict:
        cap = self.capacity
        mx = min(self.max_demand, cap)
        out = {
            "capacite_m3": cap,
            "centre": [round(v, 2) for v in self.centre],
            "bruleurs": [list(b["pos"]) for b in self.burners],
            "demande_max": round(self.max_demand, 2),
            "volume_max": round(mx, 2),
            "portance_max": round(mx * lift_strength, 2),
            "sature": self.max_demand > cap,
            "sous_exploitee": bool(cap > 0 and self.max_demand < cap * 0.5),
        }
        if quantity is not None:
            out["volume_actuel"] = round(quantity, 2)
            out["remplissage"] = round(quantity / cap, 3) if cap else None
            out["portance_actuelle"] = round(quantity * lift_strength, 2)
        return out


class BalloonOrgan(Organ):
    name = "ballons"
    cost = "eleve"

    def __init__(self, model):
        super().__init__(model)
        self.pockets: list[Pocket] = []
        self.burners: list[dict] = []
        self.sensitive: frozenset[Pos] = frozenset()
        #: la zone de fuite des poches ouvertes (voir `BalloonFiller.leaks`)
        self.leak_zone: frozenset[Pos] = frozenset()
        self.fills = 0            # compteur de flood-fills, instrumente par les tests

    # -- invalidation ------------------------------------------------------
    def affected_by(self, pos: Pos) -> bool:
        # La zone de fuite AVANT tout : apres une breche, la poche retrecit et
        # son contour ne passe plus par le trou. Remettre le mur, meme par une
        # annulation, n'etait alors vu par personne, et la poche restait percee.
        return (pos in self.sensitive or pos in self.leak_zone
                or self.s.name(pos) in BURNER_BLOCKS)

    def apply_delta(self, edits: list[Edit]) -> bool:
        """Ne relance le remplissage que sur les poches reellement touchees."""
        # Un bloc pose dans la zone de fuite peut refermer une poche ouverte,
        # ou en faire naitre une qui s'echappait : on refait proprement. Le cas
        # est rare — il faut un ballon perce — et il ne coute qu'a ce moment-la.
        if any(e.pos in self.leak_zone for e in edits):
            return False
        touched = [e for e in edits
                   if e.pos in self.sensitive or self.s.name(e.pos) in BURNER_BLOCKS]
        if not touched:
            return True                       # aucun flood-fill : rien a refaire

        # un bruleur pose ou retire peut creer ou supprimer une poche
        for e in touched:
            for entry in (e.before, e.after):
                if entry and entry["name"] in BURNER_BLOCKS:
                    return False

        affected = [p for p in self.pockets
                    if any(e.pos in p.cells or e.pos in p.shell for e in touched)]
        if not affected:
            # bloc etanche hors de toute poche : rien a reconstruire
            return True
        if len(affected) == len(self.pockets):
            return False                      # autant refaire proprement

        keep = [p for p in self.pockets if p not in affected]
        leaks_before = self.leak_zone
        rebuilt = self._build_pockets([b for p in affected for b in p.burners],
                                      avoid=set().union(*(p.cells for p in keep))
                                      if keep else set())
        self.leak_zone = leaks_before | self.leak_zone
        self.pockets = keep + rebuilt
        self.pockets.sort(key=lambda p: p.centre)
        self._build_sensitive()
        return True

    # -- construction ------------------------------------------------------
    def recompute(self) -> None:
        self.burners = self._collect_burners()
        self.leak_zone = frozenset()
        self.pockets = self._build_pockets(self.burners, avoid=set())
        self.pockets.sort(key=lambda p: p.centre)
        self._build_sensitive()

    def _collect_burners(self) -> list[dict]:
        default_max = self.tables.get("forces.burner_max_hot_air")
        out: list[dict] = []
        for name in BURNER_BLOCKS:
            fallback = DEFAULT_SCROLL[name]
            fallback = default_max if fallback is None else fallback
            for pos in sorted(self.s.positions_of(name)):
                nbt = self.s.blocks[pos].get("nbt") or {}
                out.append({"pos": pos, "bloc": name,
                            "reglage": float(nbt.get("ScrollValue", fallback)),
                            "signal": int(nbt.get("SignalStrength", 0) or 0)})
        return out

    def _build_pockets(self, burners: list[dict], avoid: set[Pos]) -> list[Pocket]:
        if not burners:
            return []
        filler = BalloonFiller(self.s, self.props, main=avoid)
        try:
            return self._fill_pockets(filler, burners)
        finally:
            self.leak_zone = frozenset(self.leak_zone | filler.leaks)

    def _fill_pockets(self, filler: "BalloonFiller",
                      burners: list[dict]) -> list[Pocket]:
        groups: list[tuple[set[Pos], list[dict]]] = []
        for br in burners:
            cast = self.cast_position(br["pos"])
            br["cast"] = cast
            if cast is None:
                continue
            existing = next((g for g in groups if cast in g[0]), None)
            if existing is not None:
                existing[1].append(br)
                continue
            self.fills += 1
            cells = filler.build(cast)
            if cells is None:
                continue
            groups.append((cells, [br]))

        pockets: list[Pocket] = []
        for cells, group in groups:
            air = [p for p in cells if self.s.is_air(p)]
            if not air:
                continue
            n = len(air)
            centre = tuple(sum(p[i] + 0.5 for p in air) / n for i in range(3))
            pocket = Pocket(cells, air, centre, group)
            pocket.build_shell()
            pockets.append(pocket)
        return pockets

    def cast_position(self, pos: Pos) -> Pos | None:
        """Raycast vers le haut depuis le bruleur (`getRaycastedPosition`).

        Renvoie le bloc situe juste sous le premier bloc plein rencontre, a
        condition que ce bloc soit etanche."""
        s = self.s
        reach = int(self.tables.get("forces.burner_max_range"))
        x, y, z = pos
        for dy in range(1, reach + 1):
            probe = (x, y + dy, z)
            if not s.inside(probe):
                return None
            if s.is_air(probe):
                continue
            name = s.name(probe)
            if not self.props.has_collision(name):
                continue
            return (x, y + dy - 1, z) if self.props.is_airtight(name) else None
        return None

    def _build_sensitive(self) -> None:
        sensitive: set[Pos] = set()
        for name in list(self.s.by_name):
            if self.props.is_airtight(name):
                sensitive |= self.s.by_name[name]
        for p in self.pockets:
            sensitive |= p.cells
            sensitive |= p.shell
        for b in self.burners:
            sensitive.add(b["pos"])
        self.sensitive = frozenset(sensitive)

    # -- lecture -----------------------------------------------------------
    @property
    def total_capacity(self) -> int:
        return sum(p.capacity for p in self.pockets)

    def report(self, quantities: list[float] | None = None) -> list[dict]:
        lift = self.tables.get("forces.hot_air_strength")
        out = []
        for i, p in enumerate(self.pockets):
            q = quantities[i] if quantities is not None and i < len(quantities) else None
            out.append(p.report(lift, q))
        return out
