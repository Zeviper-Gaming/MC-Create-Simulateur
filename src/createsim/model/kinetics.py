"""Reseau cinetique : qui entraine qui, et dans quel rapport.

Cout faible, propagation locale. Invalide si le bloc touche est cinetique, ou
voisin d'un bloc cinetique.

Ce module porte la TOPOLOGIE, qui est du modele : elle ne bouge que si on edite
un bloc. Les regimes, eux, dependent des signaux de commande et se resolvent a
chaque tick — ils sont dans la couche simulation.

Rapports d'apres Create `RotationPropagator.getRotationSpeedModifier()`.
"""
from __future__ import annotations

from collections import defaultdict

from ..data.nbt import Pos, SIX, axis_of
from .vehicle import Organ

AXES = ("x", "y", "z")

SHAFT_LIKE = frozenset((
    "create:shaft", "create:andesite_encased_shaft", "create:brass_encased_shaft",
    "create:gearbox", "create:vertical_gearbox", "create:speedometer",
    "create:stressometer", "create:gearshift", "create:clutch",
    "create:windmill_bearing", "create:mechanical_bearing",
    "create:water_wheel", "create:large_water_wheel", "create:hand_crank",
    "aeronautics:propeller_bearing", "aeronautics:gyroscopic_propeller_bearing",
    "simulated:analog_transmission", "simulated:directional_gearshift",
    "offroad:wheel_mount", "offroad:borehead_bearing",
))
SMALL_COGS = frozenset(("create:cogwheel", "create:andesite_encased_cogwheel",
                        "create:brass_encased_cogwheel"))
LARGE_COGS = frozenset(("create:large_cogwheel",
                        "create:andesite_encased_large_cogwheel",
                        "create:brass_encased_large_cogwheel"))

ANALOG_TRANSMISSION = "simulated:analog_transmission"


class Source:
    """Une source de rotation, et ce dont son regime depend."""

    __slots__ = ("pos", "block", "kind", "rpm", "sails")

    def __init__(self, pos: Pos, block: str, kind: str, rpm: float,
                 sails: int | None = None):
        self.pos = pos
        self.block = block
        self.kind = kind
        self.rpm = rpm
        self.sails = sails

    def report(self) -> dict:
        return {"pos": list(self.pos), "bloc": self.block,
                "rpm": self.rpm, "voiles": self.sails}


class KineticOrgan(Organ):
    name = "cinetique"
    cost = "faible"
    depends = ("paliers",)

    def __init__(self, model):
        super().__init__(model)
        self.nodes: dict[Pos, dict] = {}
        self.adj: dict[Pos, list[tuple[Pos, float]]] = {}
        self.sources: list[Source] = []
        self.components: list[list[Pos]] = []
        self.comp_of: dict[Pos, int] = {}
        self.recorded: dict[Pos, float] = {}
        self.sensitive: frozenset[Pos] = frozenset()

    # -- invalidation ------------------------------------------------------
    def affected_by(self, pos: Pos) -> bool:
        return pos in self.sensitive or self.is_kinetic(self.s.name(pos))

    def is_kinetic(self, name: str) -> bool:
        return (name in SHAFT_LIKE or name in SMALL_COGS or name in LARGE_COGS
                or self.props.stress_impact(name) > 0
                or self.props.stress_capacity(name) > 0
                or name.endswith("_envelope_encased_shaft")
                or name.endswith("_portable_engine")
                or name.endswith("universal_joint"))

    # -- construction ------------------------------------------------------
    def recompute(self) -> None:
        s = self.s
        self.nodes = {p: b for p, b in s.blocks.items() if self.is_kinetic(b["name"])}
        adj: dict[Pos, list[tuple[Pos, float]]] = defaultdict(list)

        for p in self.nodes:
            for d in SIX:
                q = (p[0] + d[0], p[1] + d[1], p[2] + d[2])
                if q not in self.nodes:
                    continue
                r = self._edge_ratio(p, q, d)
                if r:
                    adj[p].append((q, r))

        # engrenement en diagonale, dans le plan perpendiculaire a l'axe
        for p, b in self.nodes.items():
            if b["name"] not in LARGE_COGS and b["name"] not in SMALL_COGS:
                continue
            ax = axis_of(b)
            if not ax:
                continue
            perp = [a for a in AXES if a != ax]
            for s1 in (-1, 1):
                for s2 in (-1, 1):
                    off = {perp[0]: s1, perp[1]: s2, ax: 0}
                    q = (p[0] + off.get("x", 0), p[1] + off.get("y", 0),
                         p[2] + off.get("z", 0))
                    nb = self.nodes.get(q)
                    if not nb or axis_of(nb) != ax:
                        continue
                    r = self._edge_ratio(p, q, (0, 0, 0))
                    if r:
                        adj[p].append((q, r))

        self.adj = dict(adj)
        self._build_components()
        self._build_sources()
        self._build_sensitive()
        self.recorded = self._recorded_speeds()

    def _edge_ratio(self, p: Pos, q: Pos, d) -> float | None:
        """Rapport de vitesse de p vers q, ou None s'il n'y a pas d'accouplement."""
        t = self.tables
        bp, bq = self.nodes[p], self.nodes[q]
        np_, nq = bp["name"], bq["name"]
        ap, aq = axis_of(bp), axis_of(bq)
        d_axis = "x" if d[0] else ("y" if d[1] else "z")

        p_small, q_small = np_ in SMALL_COGS, nq in SMALL_COGS
        p_large, q_large = np_ in LARGE_COGS, nq in LARGE_COGS

        if p_large and q_small:
            return t.get("kinetics.ratio_large_to_small_cog")
        if p_small and q_large:
            return t.get("kinetics.ratio_small_to_large_cog")
        if p_large and q_large:
            return t.get("kinetics.ratio_large_to_large_cog")
        if p_small and q_small:
            if ap and ap == aq and d_axis != ap:
                return t.get("kinetics.ratio_small_to_small_cog")
            return None

        if "analog_transmission" in (np_.split(":")[-1], nq.split(":")[-1]):
            if (p_small or q_small) and ap and ap == aq and d_axis != ap:
                return t.get("kinetics.ratio_small_to_small_cog")

        if "gearbox" in np_ or "gearbox" in nq:
            gb_axis = ap if "gearbox" in np_ else aq
            return t.get("kinetics.ratio_shaft") if d_axis != gb_axis else None

        if ap and ap == d_axis and (aq == d_axis or aq is None):
            return t.get("kinetics.ratio_shaft")
        if ap is None or aq is None:
            return t.get("kinetics.ratio_shaft")
        return None

    def _build_components(self) -> None:
        parent = {p: p for p in self.nodes}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for p, edges in self.adj.items():
            for q, _r in edges:
                ra, rb = find(p), find(q)
                if ra != rb:
                    parent[rb] = ra

        groups: dict[Pos, list[Pos]] = defaultdict(list)
        for p in self.nodes:
            groups[find(p)].append(p)
        self.components = [sorted(v) for v in groups.values()]
        self.components.sort()
        self.comp_of = {p: i for i, cells in enumerate(self.components) for p in cells}

    def _build_sources(self) -> None:
        t = self.tables
        gens = t.get("kinetics.generators")
        bearings = self.model.organs.get("paliers")
        sails_per_rpm = t.get("kinetics.windmill_sails_per_rpm")
        min_sails = t.get("kinetics.windmill_min_sails")
        max_rpm = t.get("kinetics.windmill_max_rpm")

        out: list[Source] = []
        for pos, b in sorted(self.nodes.items()):
            name = b["name"]
            spec = gens.get(name)
            if name == "create:windmill_bearing":
                bearing = bearings.at(pos) if bearings else None
                sails = bearing.sails if bearing else 0
                rpm = windmill_rpm(sails, sails_per_rpm, min_sails, max_rpm)
                if rpm:
                    out.append(Source(pos, name, "voiles", rpm, sails))
                continue
            if spec and spec.get("kind") == "fixed":
                out.append(Source(pos, name, "fixe", float(spec["rpm"])))
                continue
            if name.endswith("_portable_engine"):
                out.append(Source(pos, name, "fixe",
                                  float(t.get("kinetics.portable_engine_rpm"))))
        self.sources = out

    def _build_sensitive(self) -> None:
        sensitive: set[Pos] = set()
        for p in self.nodes:
            sensitive.add(p)
            for d in SIX:
                sensitive.add((p[0] + d[0], p[1] + d[1], p[2] + d[2]))
            b = self.nodes[p]
            if b["name"] in SMALL_COGS or b["name"] in LARGE_COGS:
                ax = axis_of(b)
                if ax:
                    perp = [a for a in AXES if a != ax]
                    for s1 in (-1, 1):
                        for s2 in (-1, 1):
                            off = {perp[0]: s1, perp[1]: s2, ax: 0}
                            sensitive.add((p[0] + off.get("x", 0),
                                           p[1] + off.get("y", 0),
                                           p[2] + off.get("z", 0)))
        self.sensitive = frozenset(sensitive)

    def _recorded_speeds(self) -> dict[Pos, float]:
        """Regimes reellement mesures par le jeu, quand la structure a ete
        sauvegardee moteur tournant. C'est une verite terrain : elle sert a
        valider le solveur, et elle est gratuite."""
        out: dict[Pos, float] = {}
        for pos, b in self.s.blocks.items():
            nbt = b.get("nbt")
            if not nbt:
                continue
            v = nbt.get("Speed")
            if isinstance(v, (int, float)) and abs(v) > 1e-9:
                out[pos] = float(v)
        return out


def windmill_rpm(sails: int, sails_per_rpm: int = 8, minimum_sails: int = 8,
                 max_rpm: int = 16) -> float:
    """Create `WindmillBearingBlockEntity.getGeneratedSpeed()`."""
    if sails < minimum_sails:
        return 0.0
    return float(min(max(sails // sails_per_rpm, 1), max_rpm))


def analog_transmission_ratio(signal: int) -> dict:
    """`AnalogTransmissionBlockEntity`. Le decouplage a 15 est ecrit en toutes
    lettres : c'est le piege que le bandeau doit lever."""
    if signal <= 0:
        return {"mode": "prise directe", "reduction": 1.0, "augmentation": 1.0}
    if signal >= 15:
        return {"mode": "decouple", "reduction": None, "augmentation": None}
    return {"mode": "actif", "reduction": (15 - signal) / 16.0,
            "augmentation": 16.0 / (15 - signal)}
