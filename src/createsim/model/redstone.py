"""Topologie des commandes : du levier a l'organe, par les liaisons redstone.

En jeu, cette topologie est invisible. C'est elle qui repond a « qu'est-ce que
fait ce levier ? » et qui permet de mettre en surbrillance les destinataires
d'une commande (F4.3).

Le piege `inverted` du Throttle Lever est traite ici. `ThrottleLeverBlock
.getSignal()` renvoie `state` directement ; la propriete `inverted` n'affecte
QUE l'angle affiche (`15 - state`). Consequence : manette visuellement au neutre
sur un levier inverse, c'est `State = 15`, donc transmission DECOUPLEE.
"""
from __future__ import annotations

from collections import defaultdict

from ..data.nbt import Pos, SIX
from .vehicle import Organ

ANALOG_LEVER = "create:analog_lever"
THROTTLE_LEVER = "simulated:throttle_lever"
VANILLA_LEVER = "minecraft:lever"
LEVER_BLOCKS = (ANALOG_LEVER, THROTTLE_LEVER, VANILLA_LEVER)

REDSTONE_LINK = "create:redstone_link"
BURNERS = ("aeronautics:adjustable_burner", "aeronautics:steam_vent")
TRANSMISSIONS = ("simulated:analog_transmission",)
CONSUMERS = BURNERS + TRANSMISSIONS

FACING_VEC = {"east": (1, 0, 0), "west": (-1, 0, 0), "up": (0, 1, 0),
              "down": (0, -1, 0), "south": (0, 0, 1), "north": (0, 0, -1)}


def attachment(pos: Pos, name: str, props: dict) -> Pos | None:
    """Le bloc auquel un levier ou une liaison est accroche.

    C'est la clef du couplage : un levier alimente le bloc qu'il touche, et une
    liaison emettrice lit l'alimentation du bloc qu'elle touche. Quand les deux
    designent le MEME bloc, le levier pilote la liaison — meme si les deux ne
    sont pas voisins. Sur `cargo_airship`, la manette est deux blocs au-dessus
    de son emetteur, et c'est exactement ce cas.

    `physique-moteur.md` §11 : redstone_link accroche a l'oppose de son facing ;
    bloc FaceAttached (levier, bouton, analog/throttle lever) selon sa `face`.
    """
    if name == REDSTONE_LINK:
        vec = FACING_VEC.get(props.get("facing"))
        return None if vec is None else (pos[0] - vec[0], pos[1] - vec[1],
                                         pos[2] - vec[2])
    face = props.get("face")
    if face == "floor":
        return (pos[0], pos[1] - 1, pos[2])
    if face == "ceiling":
        return (pos[0], pos[1] + 1, pos[2])
    vec = FACING_VEC.get(props.get("facing"))
    if vec is None:
        return None
    return (pos[0] - vec[0], pos[1] - vec[1], pos[2] - vec[2])


class Lever:
    """Une commande de bord, telle qu'elle existe dans la structure."""

    __slots__ = ("pos", "block", "initial", "inverted", "targets", "attach")

    def __init__(self, pos: Pos, block: str, initial: int, inverted: bool,
                 attach: Pos | None = None):
        self.pos = pos
        self.block = block
        self.initial = initial
        self.inverted = inverted
        self.attach = attach
        self.targets: set[Pos] = set()

    def displayed_angle(self, signal: int) -> int:
        """L'angle que montre le jeu — different du signal si `inverted`."""
        return 15 - signal if self.inverted else signal

    def report(self, signal: int | None = None) -> dict:
        s = self.initial if signal is None else signal
        out = {"pos": list(self.pos), "bloc": self.block, "signal": s,
               "angle_affiche": self.displayed_angle(s), "inverse": self.inverted,
               "commande": [list(p) for p in sorted(self.targets)]}
        if self.inverted:
            out["piege"] = ("levier inverse : l'angle affiche vaut 15 - signal ; "
                            "manette au neutre a l'ecran = signal 15 = decouple")
        return out


class RedstoneOrgan(Organ):
    name = "redstone"
    cost = "faible"

    def __init__(self, model):
        super().__init__(model)
        self.levers: list[Lever] = []
        self.channels: dict[tuple, dict] = {}
        self.link_attach: dict[Pos, Pos | None] = {}
        self.consumers: dict[Pos, str] = {}
        self.initial_signal: dict[Pos, int] = {}
        self.driven: set[Pos] = set()
        self.channel_of: dict[Pos, tuple] = {}
        self.levers_of: dict[Pos, list[Pos]] = {}
        self.sensitive: frozenset[Pos] = frozenset()

    def affected_by(self, pos: Pos) -> bool:
        return pos in self.sensitive or self.s.name(pos) in (
            LEVER_BLOCKS + (REDSTONE_LINK,) + CONSUMERS)

    # -- construction ------------------------------------------------------
    def recompute(self) -> None:
        s = self.s
        self.levers = []
        self.consumers = {}
        self.initial_signal = {}

        for name in LEVER_BLOCKS:
            for pos in sorted(s.positions_of(name)):
                b = s.blocks[pos]
                nbt = b.get("nbt") or {}
                props = b["props"]
                if name == VANILLA_LEVER:
                    state = 15 if props.get("powered") == "true" else 0
                    inverted = False
                else:
                    state = int(nbt.get("State", 0))
                    inverted = _truthy(nbt.get("inverted", props.get("inverted")))
                self.levers.append(
                    Lever(pos, name, state, inverted, attachment(pos, name, props)))

        for name in CONSUMERS:
            for pos in sorted(s.positions_of(name)):
                nbt = s.blocks[pos].get("nbt") or {}
                self.consumers[pos] = name
                key = "Signal" if name in TRANSMISSIONS else "SignalStrength"
                self.initial_signal[pos] = int(nbt.get(key, 0) or 0)

        self._build_channels()
        self._build_targets()
        self._build_sensitive()

    def _build_channels(self) -> None:
        channels: dict[tuple, dict] = defaultdict(lambda: {"tx": [], "rx": []})
        self.link_attach = {}
        for pos in sorted(self.s.positions_of(REDSTONE_LINK)):
            b = self.s.blocks[pos]
            nbt = b.get("nbt") or {}
            key = _frequency(nbt)
            side = "tx" if nbt.get("Transmitter") else "rx"
            channels[key][side].append(pos)
            self.link_attach[pos] = attachment(pos, REDSTONE_LINK, b["props"])
        self.channels = dict(channels)

    def _build_targets(self) -> None:
        # ce que chaque canal alimente, par ses recepteurs
        per_channel: dict[tuple, set[Pos]] = {}
        self.channel_of = {}
        for key, sides in self.channels.items():
            reached: set[Pos] = set()
            for rx in sides["rx"]:
                reached |= self._consumers_near(rx, self.link_attach.get(rx))
            per_channel[key] = reached
            for consumer in reached:
                self.channel_of.setdefault(consumer, key)

        driven: set[Pos] = set()
        for lever in self.levers:
            targets = self._consumers_near(lever.pos, lever.attach)
            for key, sides in self.channels.items():
                if any(self._drives(lever, tx) for tx in sides["tx"]):
                    targets |= per_channel[key]
            lever.targets = targets
            driven |= targets
        self.driven = driven
        self.levers_of = {}
        for lever in self.levers:
            for target in lever.targets:
                self.levers_of.setdefault(target, []).append(lever.pos)

    def _drives(self, lever: Lever, tx: Pos) -> bool:
        """Un levier pilote un emetteur s'ils alimentent le meme bloc."""
        tx_attach = self.link_attach.get(tx)
        if lever.attach is not None and lever.attach == tx_attach:
            return True
        if _adjacent(tx, lever.pos):
            return True
        return lever.attach is not None and _adjacent(tx, lever.attach)

    def _consumers_near(self, pos: Pos, attach: Pos | None) -> set[Pos]:
        out: set[Pos] = set()
        for d in SIX:
            q = (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])
            if q in self.consumers:
                out.add(q)
        if attach is not None and attach in self.consumers:
            out.add(attach)
        return out

    def _build_sensitive(self) -> None:
        sensitive: set[Pos] = set()
        interesting = (set(self.consumers) | {lv.pos for lv in self.levers}
                       | set(self.s.positions_of(REDSTONE_LINK)))
        for p in interesting:
            sensitive.add(p)
            for d in SIX:
                sensitive.add((p[0] + d[0], p[1] + d[1], p[2] + d[2]))
        self.sensitive = frozenset(sensitive)

    # -- service au tick ---------------------------------------------------
    def signals(self, commands: dict[Pos, int]) -> dict[Pos, int]:
        """Signal recu par chaque consommateur, d'apres l'etat des leviers.

        Un consommateur qu'aucun levier n'atteint garde le signal enregistre
        dans le NBT : la mesure du jeu prime sur le calcul, et inventer un zero
        ferait disparaitre un bruleur qui, en jeu, chauffe.
        """
        out = dict(self.initial_signal)
        for lever in self.levers:
            if not lever.targets:
                continue
            value = int(commands.get(lever.pos, lever.initial))
            for target in lever.targets:
                out[target] = value
        return out

    @property
    def uncommanded(self) -> list[Pos]:
        """Consommateurs qu'aucun levier n'atteint — a signaler, pas a masquer."""
        return sorted(set(self.consumers) - self.driven)

    def concordance(self) -> dict:
        """Compare la topologie deduite au signal enregistre dans le NBT.

        Meme discipline que pour la cinetique : le jeu fournit sa verite terrain,
        on publie le score au lieu de le masquer. Un ecart est une limite du
        modele de redstone, pas un defaut du vaisseau."""
        predicted = self.signals({lv.pos: lv.initial for lv in self.levers})
        agree, ecarts = 0, []
        for pos in sorted(self.driven):
            want = self.initial_signal.get(pos, 0)
            got = predicted.get(pos, 0)
            if got == want:
                agree += 1
            elif len(ecarts) < 12:
                ecarts.append({"pos": list(pos), "bloc": self.consumers[pos],
                               "enregistre": want, "deduit": got})
        return {
            "commandes_resolues": "%d/%d" % (agree, len(self.driven)),
            "consommateurs": len(self.consumers),
            "pilotes": len(self.driven),
            "ecarts": ecarts,
            "sans_commande": [list(p) for p in self.uncommanded],
            "limite": (
                "les consommateurs sans commande gardent le signal du NBT : "
                "c'est une limite du modele de redstone, pas un defaut du vaisseau"
                if self.uncommanded else None),
        }

    def report(self, commands: dict[Pos, int] | None = None) -> dict:
        commands = commands or {}
        signals = self.signals(commands)
        return {
            "commandes": [lv.report(commands.get(lv.pos, lv.initial))
                          for lv in self.levers],
            "canaux": len(self.channels),
            "consommateurs": len(self.consumers),
            "sans_commande": [list(p) for p in self.uncommanded],
            "signaux": {str(list(p)): v for p, v in sorted(signals.items())},
        }


def _adjacent(a: Pos, b: Pos) -> bool:
    return sum(abs(a[i] - b[i]) for i in range(3)) == 1


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).lower() in ("1", "true", "yes")


def _frequency(nbt: dict) -> tuple:
    def item(tag):
        d = nbt.get(tag) or {}
        return d.get("id", "minecraft:air") if isinstance(d, dict) else "minecraft:air"
    return (item("FrequencyFirst"), item("FrequencyLast"))
