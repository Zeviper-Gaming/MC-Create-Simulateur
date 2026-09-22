"""Reseau cinetique : qui entraine qui, et dans quel rapport.

Cout faible, propagation locale. Invalide si le bloc touche est cinetique, ou
voisin d'un bloc cinetique.

Ce module porte la TOPOLOGIE, qui est du modele : elle ne bouge que si on edite
un bloc. Les regimes, eux, dependent des signaux de commande et se resolvent a
chaque tick — ils sont dans la couche simulation.

Rapports d'apres Create `RotationPropagator.getRotationSpeedModifier()`.
"""
from __future__ import annotations

from collections import defaultdict, deque

from ..data.nbt import Pos, SIX, axis_of
from .vehicle import Organ

AXES = ("x", "y", "z")

SHAFT_LIKE = frozenset((
    "create:shaft", "create:andesite_encased_shaft", "create:brass_encased_shaft",
    "create:gearbox", "create:vertical_gearbox", "create:speedometer",
    "create:stressometer", "create:gearshift", "create:clutch",
    "create:windmill_bearing", "create:mechanical_bearing",
    "create:water_wheel", "create:large_water_wheel", "create:hand_crank",
    "create:creative_motor", "create:encased_chain_drive",
    "create:rotation_speed_controller", "create:gantry_shaft",
    "aeronautics:propeller_bearing", "aeronautics:gyroscopic_propeller_bearing",
    "simulated:analog_transmission", "simulated:directional_gearshift",
    "offroad:wheel_mount", "offroad:borehead_bearing",
))

CHAIN_DRIVES = frozenset(("create:encased_chain_drive",))

# Un embrayage alimente coupe la transmission.
# Un aiguillage alimente inverse le sens : non modelise, il ne change que le
# signe de la poussee, dont la convention a ete confrontee au jeu
# (`data/mesures/jeu.json`).
CLUTCHES = frozenset(("create:clutch",))
SMALL_COGS = frozenset(("create:cogwheel", "create:andesite_encased_cogwheel",
                        "create:brass_encased_cogwheel"))
LARGE_COGS = frozenset(("create:large_cogwheel",
                        "create:andesite_encased_large_cogwheel",
                        "create:brass_encased_large_cogwheel"))

ANALOG_TRANSMISSION = "simulated:analog_transmission"


def gearbox_modifier(entree: Pos, sortie: Pos) -> int:
    """Le signe qu'une boite de vitesses impose, `RotationPropagator` offset 31.

        meme axe          : +1 si meme direction, -1 sinon
        axes differents   : -1 si les deux directions d'axe s'accordent, +1 sinon

    Autrement dit une boite RENVERSE la rotation en ligne droite, et croise les
    sens en perpendiculaire. `entree` est la direction de la boite VERS sa
    source (`getSourceFacing`), `sortie` celle vers le bloc entraine.

    Le signe depend donc de la face par ou la rotation ENTRE, pas seulement de
    l'arete : deux boites identiques cote a cote n'ont pas le meme effet selon
    d'ou vient le mouvement. C'est ce qui manquait au solveur, et ce qui lui
    faisait rendre 24 regimes de signe oppose au releve sur le cachalot.
    """
    axe_e = next((i for i in range(3) if entree[i]), None)
    axe_s = next((i for i in range(3) if sortie[i]), None)
    if axe_e is None or axe_s is None:
        return 1
    if axe_e == axe_s:
        return 1 if entree[axe_e] == sortie[axe_s] else -1
    return -1 if (entree[axe_e] > 0) == (sortie[axe_s] > 0) else 1


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
        self.transmission_sides: dict[tuple[Pos, Pos], str] = {}
        self.sensitive: frozenset[Pos] = frozenset()
        #: positions des boites de vitesses : leur signe depend de la face
        #: d'entree, donc il ne tient pas dans le poids d'une arete
        self.gearboxes: frozenset[Pos] = frozenset()
        #: signe a injecter a chaque source pour que le reseau tourne dans le
        #: sens que le jeu a enregistre. Voir `_build_orientation`.
        self.source_sign: dict[Pos, int] = {}
        #: index des reseaux dont le SENS absolu est ancre par un releve
        self.oriented: set[int] = set()
        #: reseaux ou le releve se contredit lui-meme (topologie douteuse)
        self.sign_conflicts: list[dict] = []

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
        sides: dict[tuple[Pos, Pos], str] = {}

        for p in self.nodes:
            for d in SIX:
                q = (p[0] + d[0], p[1] + d[1], p[2] + d[2])
                if q not in self.nodes:
                    continue
                r, side = self._edge_ratio(p, q, d)
                if r:
                    adj[p].append((q, r))
                    if side:
                        sides[(p, q)] = side

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
                    r, side = self._edge_ratio(p, q, (0, 0, 0))
                    if r:
                        adj[p].append((q, r))
                        if side:
                            sides[(p, q)] = side

        # Chaines : deux entrainements voisins tournent a l'identique quand la
        # direction qui les separe est perpendiculaire a leurs deux axes. Sans
        # cela, 147 blocs du c1_air_cruiser restent hors du reseau, et les
        # helices de queue n'ont aucune source.
        for p, b in self.nodes.items():
            if b["name"] not in CHAIN_DRIVES:
                continue
            ap = axis_of(b)
            if not ap:
                continue
            for d in SIX:
                q = (p[0] + d[0], p[1] + d[1], p[2] + d[2])
                nb = self.nodes.get(q)
                if not nb or nb["name"] not in CHAIN_DRIVES:
                    continue
                aq = axis_of(nb)
                d_axis = "x" if d[0] else ("y" if d[1] else "z")
                if aq and d_axis != ap and d_axis != aq:
                    adj[p].append((q, 1.0))

        self.adj = dict(adj)
        self.gearboxes = frozenset(p for p, b in self.nodes.items()
                                   if "gearbox" in b["name"])
        self.transmission_sides = sides
        self._build_components()
        self._build_sources()
        self._build_sensitive()
        self.recorded = self._recorded_speeds()
        self._build_orientation()

    def _edge_ratio(self, p: Pos, q: Pos, d):
        """Rapport de vitesse de p vers q, et le cote de transmission traverse.

        Renvoie `(ratio, cote)`, ou `(None, None)` s'il n'y a pas d'accouplement.
        `cote` vaut None sauf quand l'arete franchit une transmission analogique :
        son rapport depend du signal, qui change en cours de simulation, donc il
        est applique au tick et non fige dans la topologie.
        """
        t = self.tables
        bp, bq = self.nodes[p], self.nodes[q]
        np_, nq = bp["name"], bq["name"]

        # Un embrayage alimente coupe la transmission : sans cela le solveur
        # entraine tout un arbre que le jeu laisse a l'arret.
        if ((np_ in CLUTCHES and _powered(bp))
                or (nq in CLUTCHES and _powered(bq))):
            return None, None

        ap, aq = axis_of(bp), axis_of(bq)
        d_axis = "x" if d[0] else ("y" if d[1] else "z")

        # --- transmission analogique : un cote arbre, un cote roue dentee ----
        # Le bloc siege a la vitesse de son ARBRE ; sa roue dentee integree
        # (`ExtraCogwheel` dans le NBT) tourne a (15 - signal)/16 de celle-ci.
        # Verifie sur trois vaisseaux : 16 -> 21,33 au signal 3 (c1_air_cruiser),
        # 32 -> 4 au signal 13 (sledoger_t), 64 -> 170,67 au signal 9 (dirt_bike).
        if np_ == ANALOG_TRANSMISSION or nq == ANALOG_TRANSMISSION:
            if np_ == ANALOG_TRANSMISSION and nq == ANALOG_TRANSMISSION:
                return None, None
            if np_ == ANALOG_TRANSMISSION:
                axis, outgoing = ap, True
            else:
                axis, outgoing = aq, False
            if axis and d_axis == axis:
                return t.get("kinetics.ratio_shaft"), None       # cote arbre
            meshing = t.get("kinetics.ratio_small_to_small_cog")
            return meshing, ("arbre_vers_roue" if outgoing else "roue_vers_arbre")

        p_small, q_small = np_ in SMALL_COGS, nq in SMALL_COGS
        p_large, q_large = np_ in LARGE_COGS, nq in LARGE_COGS

        if p_large and q_small:
            return t.get("kinetics.ratio_large_to_small_cog"), None
        if p_small and q_large:
            return t.get("kinetics.ratio_small_to_large_cog"), None
        if p_large and q_large:
            return t.get("kinetics.ratio_large_to_large_cog"), None
        if p_small and q_small:
            if ap and ap == aq and d_axis != ap:
                return t.get("kinetics.ratio_small_to_small_cog"), None
            return None, None

        if "analog_transmission" in (np_.split(":")[-1], nq.split(":")[-1]):
            if (p_small or q_small) and ap and ap == aq and d_axis != ap:
                return t.get("kinetics.ratio_small_to_small_cog"), None

        # Boite de vitesses : elle presente une face d'arbre dans les quatre
        # directions perpendiculaires a son axe, et rien le long de son axe.
        # Le voisin doit lui aussi presenter un BOUT dans cette direction : un
        # arbre pose en x ne se branche pas sous une boite par le dessus.
        # Sans cette seconde condition, le solveur entraine a 256 tr/min une
        # branche que le jeu laisse a l'arret (cachalot_volant_v3, x=63).
        p_gearbox, q_gearbox = "gearbox" in np_, "gearbox" in nq
        if p_gearbox or q_gearbox:
            if p_gearbox and d_axis == ap:
                return None, None
            if q_gearbox and d_axis == aq:
                return None, None
            if not p_gearbox and ap is not None and ap != d_axis:
                return None, None
            if not q_gearbox and aq is not None and aq != d_axis:
                return None, None
            return t.get("kinetics.ratio_shaft"), None

        if ap and ap == d_axis and (aq == d_axis or aq is None):
            return t.get("kinetics.ratio_shaft"), None
        if ap is None or aq is None:
            return t.get("kinetics.ratio_shaft"), None
        return None, None

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
                if bearing is not None and bearing.assembled:
                    # Rotor assemble : ses voiles ne sont pas dans le fichier.
                    # Le jeu fournit sa propre verite terrain, on la reprend
                    # plutot que d'annoncer un moulin a l'arret.
                    rpm = abs(bearing.last_generated)
                    if rpm:
                        out.append(Source(pos, name, "mesure_du_jeu", rpm))
                    continue
                sails = bearing.sails if bearing else 0
                rpm = windmill_rpm(sails, sails_per_rpm, min_sails, max_rpm)
                if rpm:
                    out.append(Source(pos, name, "voiles", rpm, sails))
                continue
            if spec and spec.get("kind") == "fixed":
                out.append(Source(pos, name, "fixe", float(spec["rpm"])))
                continue
            if spec and spec.get("kind") == "nbt":
                # On lit le REGLAGE du bloc, pas sa vitesse mesuree : se servir
                # de `Speed` rendrait la concordance circulaire, puisque c'est
                # justement elle que le solveur doit retrouver.
                nbt = b.get("nbt") or {}
                value = nbt.get(spec["field"])
                if value is None and spec.get("fallback"):
                    value = nbt.get(spec["fallback"])
                if value is None:
                    value = spec.get("rpm")
                rpm = abs(float(value or 0.0))
                doubler = spec.get("doubler")
                if doubler and nbt.get(doubler):
                    # Un moteur surchauffe double sa sortie : c'est l'etage x2
                    # qui manquait au solveur.
                    rpm *= t.get("kinetics.superheated_multiplier")
                if rpm:
                    out.append(Source(pos, name, "reglage", rpm))
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

    def turn_factor(self, cur: Pos, previous: Pos | None, nxt: Pos) -> int:
        """Le signe supplementaire impose par `cur` quand il entraine `nxt`.

        Neutre partout sauf sur une boite de vitesses, dont la regle depend de
        la face d'entree."""
        if previous is None or cur not in self.gearboxes:
            return 1
        entree = tuple(previous[i] - cur[i] for i in range(3))
        sortie = tuple(nxt[i] - cur[i] for i in range(3))
        return gearbox_modifier(entree, sortie)

    def _relative_signs(self, start: Pos) -> dict[Pos, int]:
        """Sens de rotation de chaque bloc, relativement a `start`.

        Le point de depart n'est PAS arbitraire : une boite de vitesses impose
        un signe qui depend de la face par ou la rotation entre, donc l'arbre
        de propagation change le resultat. On part de la source, comme le jeu —
        partir d'un coin du reseau donnait 27 signes faux sur 53.
        """
        rel: dict[Pos, int] = {start: 1}
        came_from: dict[Pos, Pos | None] = {start: None}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            for nxt, ratio in self.adj.get(cur, ()):
                # Le facteur d'une transmission analogique est toujours positif :
                # il change le regime, jamais le sens. Seul le signe du rapport
                # compte ici, plus celui que la boite de vitesses impose.
                turn = (rel[cur] * (1 if ratio > 0 else -1)
                        * self.turn_factor(cur, came_from[cur], nxt))
                if nxt in rel:
                    continue
                rel[nxt] = turn
                came_from[nxt] = cur
                queue.append(nxt)
        return rel

    def _build_orientation(self) -> None:
        """Ancre le SENS absolu de chaque reseau sur les regimes enregistres.

        Le solveur retrouvait les regimes a 0,5 tr/min pres mais partait de
        `+rpm` a chaque source : le sens absolu d'un reseau etait donc arbitraire.
        Invisible tant que rien n'en dependait — la poussee d'une helice en
        depend, parce que le palier porte une option « molette » qui renverse
        SA poussee. Deux helices du cargo, l'une en RIGHT_HANDED et l'autre en
        LEFT_HANDED, s'annulaient au lieu de s'ajouter.

        Quand le fichier a ete sauvegarde moteur tournant, il porte le sens
        reel : on s'y ancre. Sinon le sens reste inconnu, et le reseau le dit
        plutot que de faire semblant (F5.13).
        """
        self.source_sign = {}
        self.oriented = set()
        self.sign_conflicts = []
        for index in range(len(self.components)):
            sources = [s for s in self.sources if self.comp_of.get(s.pos) == index]
            if not sources:
                continue
            # le meme ordre que le solveur : c'est cette source qui enracine
            # l'arbre, et l'arbre decide des signes
            primary = max(sources, key=lambda s: abs(s.rpm))
            rel = self._relative_signs(primary.pos)

            pour = contre = 0
            for pos, measured in self.recorded.items():
                turn = rel.get(pos)
                if turn is None:
                    continue
                if (measured > 0) == (turn > 0):
                    pour += 1
                else:
                    contre += 1
            if pour or contre:
                self.oriented.add(index)
                sign = 1 if pour >= contre else -1
                if pour and contre:
                    # Le releve se contredit : notre topologie n'a pas la meme
                    # alternance que le jeu quelque part. On le DIT.
                    self.sign_conflicts.append({
                        "reseau": index, "accord": max(pour, contre),
                        "desaccord": min(pour, contre)})
            else:
                sign = 1
            for s in sources:
                self.source_sign[s.pos] = sign * rel.get(s.pos, 1)

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


def _powered(block: dict) -> bool:
    """Etat redstone d'un bloc, lu dans son blockstate."""
    return block.get("props", {}).get("powered") == "true"
