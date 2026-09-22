"""Scenarios : une execution qu'on peut refaire a l'identique (F5, lot L4).

Un scenario associe quatre choses, et il faut les quatre pour qu'une execution
soit reproductible :

    le fichier       quel vaisseau
    les reglages     quelles constantes, si on s'ecarte des valeurs sourcees
    la situation     altitude de depart, sol, gaz initial, vitesse initiale
    les commandes    une sequence HORODATEE : a quel tick quel levier bouge

Le quatrieme point est celui qui distingue un scenario d'un simple jeu de
reglages. « Brûleurs a fond » ne dit pas la meme chose que « brûleurs a fond
puis coupes a la seconde 40 », et c'est justement le genre de manoeuvre qu'on
veut pouvoir refaire apres avoir change un bloc.

Deux usages en decoulent, et ce sont eux qui justifient le lot :

    la comparaison     deux configurations du meme vaisseau, courbes superposees
    la non-regression  les scenarios de reference rejoues apres une mise a jour
                       des tables, pour voir CE QUI A BOUGE

Le second est ce qui permet de suivre un mod en alpha sans redouter chaque
version. Il n'a de sens que parce que le noyau tourne sans fenetre.

Le format est du JSON lisible a la main, comme l'exige le cahier : un scenario
se relit, se corrige et se compare dans un editeur de texte, sans l'outil.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..data.nbt import Pos
from ..data.tables import Tables
from ..model.vehicle import VehicleModel
from .state import SimOptions
from .telemetry import Trace
from .tick import Simulation

SCHEMA = 1

#: la ou chercher un vaisseau nomme par un scenario. Les fixtures du depot
#: d'abord, pour qu'un clone puisse rejouer la bibliotheque sans le jeu.
INSTANCE = Path(r"C:/Users/Florian/curseforge/minecraft/Instances"
                r"/La Bonne Compagnie/schematics")


def default_library() -> Path:
    from .. import paths
    try:
        candidate = paths.data_dir() / "scenarios"
        if candidate.is_dir():
            return candidate
    except FileNotFoundError:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "scenarios"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("data/scenarios introuvable")


def _fixtures() -> Path | None:
    """Les vaisseaux livres avec l'outil : `tests/fixtures` dans le depot,
    `exemples` dans un executable."""
    from .. import paths
    return paths.examples_dir()


def locate(name: str) -> Path | None:
    """Resout le nom d'un vaisseau, fixtures du depot d'abord."""
    if Path(name).is_file():
        return Path(name)
    for directory in (_fixtures(), INSTANCE):
        if directory is not None and (directory / name).is_file():
            return directory / name
    return None


def _slug(text: str) -> str:
    """Un nom de fichier sur : ASCII, sans accent, sans doublon de tiret."""
    normal = unicodedata.normalize("NFKD", text)
    keep = [c if c.isalnum() and c.isascii() else "-" for c in normal
            if not unicodedata.combining(c)]
    out = "".join(keep).lower()
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def parse_pos(text: str) -> Pos:
    x, y, z = (int(v) for v in str(text).replace(" ", "").split(","))
    return (x, y, z)


def format_pos(pos: Pos) -> str:
    return "%d,%d,%d" % tuple(pos)


@dataclass(frozen=True)
class Step:
    """Un mouvement de commande, date en ticks depuis le depart."""

    tick: int
    lever: Pos
    value: int

    def to_json(self) -> dict:
        return {"tick": self.tick, "levier": format_pos(self.lever),
                "valeur": self.value}

    @classmethod
    def from_json(cls, raw: dict) -> "Step":
        return cls(int(raw["tick"]), parse_pos(raw["levier"]),
                   int(raw["valeur"]))


@dataclass
class Scenario:
    """Une execution reproductible, et le sens qu'on lui donne."""

    nom: str
    vaisseau: str
    ticks: int = 1200
    options: SimOptions = field(default_factory=SimOptions)
    commandes: tuple[Step, ...] = ()
    #: overrides de tables — c'est ce qui fait « deux configurations »
    reglages: dict = field(default_factory=dict)
    echantillon: int = 1
    question: str = ""
    notes: str = ""
    #: la VARIANTE (F6.8) : des intentions d'edition, rejouees sur le fichier
    #: source avant le premier tick. Deux scenarios du meme vaisseau qui ne
    #: different que par elles se comparent courbe contre courbe.
    editions: list = field(default_factory=list)
    #: le fichier d'ou il vient, quand il en a un. C'est lui qui nomme la
    #: trace de reference : un nom derive du titre casserait des que le titre
    #: gagne un accent ou une virgule.
    path: Path | None = field(default=None, repr=False, compare=False)

    # -- fichier -----------------------------------------------------------
    def to_json(self) -> dict:
        o = self.options
        return {
            "schema": SCHEMA,
            "nom": self.nom,
            "question": self.question,
            "vaisseau": self.vaisseau,
            "ticks": self.ticks,
            "echantillon": self.echantillon,
            "situation": {
                "altitude": o.altitude,
                "vitesse_initiale": list(o.velocity),
                "sol_actif": o.ground_enabled,
                "sol_altitude": o.ground_altitude,
                "sol_friction": o.ground_friction,
                "gaz_initial": o.initial_gas,
                # Sous quelle physique la trace a ete enregistree. Une
                # bibliotheque de non-regression qui ne le dirait pas laisserait
                # croire qu'un ecart vient du vaisseau alors qu'il vient du
                # simulateur.
                "rotation": o.rotation,
            },
            "reglages": dict(sorted(self.reglages.items())),
            "editions": list(self.editions),
            "commandes": [s.to_json() for s in self.commandes],
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, raw: dict) -> "Scenario":
        s = raw.get("situation") or {}
        options = SimOptions(
            altitude=float(s.get("altitude", 63.0)),
            velocity=tuple(s.get("vitesse_initiale") or (0.0, 0.0, 0.0)),
            ground_enabled=bool(s.get("sol_actif", False)),
            ground_altitude=float(s.get("sol_altitude", 0.0)),
            ground_friction=float(s.get("sol_friction", 1.0)),
            initial_gas=str(s.get("gaz_initial", "nbt")),
            rotation=bool(s.get("rotation", True)),
        )
        return cls(
            nom=raw["nom"],
            vaisseau=raw["vaisseau"],
            ticks=int(raw.get("ticks", 1200)),
            options=options,
            commandes=tuple(Step.from_json(c) for c in raw.get("commandes") or []),
            reglages=dict(raw.get("reglages") or {}),
            editions=list(raw.get("editions") or []),
            echantillon=int(raw.get("echantillon", 1)),
            question=raw.get("question", ""),
            notes=raw.get("notes", ""),
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=1)
                        + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        path = Path(path)
        scenario = cls.from_json(json.loads(path.read_text(encoding="utf-8")))
        scenario.path = path
        return scenario

    def reference_path(self, directory: str | Path | None = None) -> Path:
        """Ou vit la trace de reference de ce scenario."""
        base = Path(directory) if directory else (
            self.path.parent if self.path else default_library())
        stem = self.path.stem if self.path else _slug(self.nom)
        return base / "references" / (stem + ".csv")

    # -- execution ---------------------------------------------------------
    def tables(self, base: Tables | None = None) -> Tables:
        """Les tables de CETTE configuration.

        Un reglage passe forcement par le mode expert : c'est lui qui marque
        toute grandeur calculee comme ne reposant plus sur les constantes du
        jeu. Un scenario regle ne doit pas pouvoir se faire passer pour une
        mesure de reference.
        """
        tables = base or Tables.load()
        if not self.reglages:
            return tables
        tables.expert_mode = True
        for key, value in self.reglages.items():
            tables.override(key, value)
        return tables

    def build(self, base: Tables | None = None) -> Simulation:
        path = locate(self.vaisseau)
        if path is None:
            raise FileNotFoundError("vaisseau introuvable : %s" % self.vaisseau)
        tables = self.tables(base)
        model = VehicleModel.load(str(path), tables)
        if self.editions:
            from .variant import apply_ops
            apply_ops(model, self.editions)
        return Simulation(model, replace(self.options))

    def run(self, base: Tables | None = None, sim: Simulation | None = None,
            trace: Trace | None = None) -> Trace:
        """Rejoue le scenario a l'identique. Aucun alea : meme entree, meme sortie."""
        sim = sim or self.build(base)
        sim.reset()
        trace = trace if trace is not None else Trace(every=self.echantillon)

        schedule: dict[int, list[Step]] = {}
        for step in self.commandes:
            schedule.setdefault(step.tick, []).append(step)

        for step in schedule.get(0, ()):
            sim.set_command(step.lever, step.value)
        trace.record(sim)
        for tick in range(1, self.ticks + 1):
            for step in schedule.get(tick, ()):
                sim.set_command(step.lever, step.value)
            sim.step()
            trace.record(sim)
        return trace

    # -- capture -----------------------------------------------------------
    @classmethod
    def from_simulation(cls, sim: Simulation, nom: str, vaisseau: str,
                        ticks: int = 1200, **kwargs) -> "Scenario":
        """Fige l'etat courant d'une session en scenario rejouable.

        Les commandes en place deviennent des pas au tick 0 : c'est ce qu'on
        veut apres avoir regle un bandeau a la main.
        """
        steps = tuple(
            Step(0, lever.pos, int(sim.state.commands.get(lever.pos,
                                                          lever.initial)))
            for lever in sim.redstone.levers)
        kwargs.setdefault("editions", _editions_of(sim.model))
        return cls(nom=nom, vaisseau=vaisseau, ticks=ticks,
                   options=replace(sim.options), commandes=steps, **kwargs)


def _editions_of(model) -> list:
    """Les editions en cours de la session, au format des scenarios."""
    from .variant import ops_to_json
    return ops_to_json(getattr(model, "ops", []))


class Recorder:
    """Enregistre les mouvements de commande d'une session en cours.

    Seul un CHANGEMENT est retenu. Consigner la position de chaque levier a
    chaque tick donnerait un fichier illisible a la main, ce que le cahier
    interdit — et rejouable a l'identique tout de meme, puisque entre deux
    changements rien ne bouge.
    """

    def __init__(self, sim: Simulation):
        self.sim = sim
        self.steps: list[Step] = []
        self.start = sim.state.tick
        self._last: dict[Pos, int] = {}
        for lever in sim.redstone.levers:
            value = int(sim.state.commands.get(lever.pos, lever.initial))
            self._last[lever.pos] = value
            self.steps.append(Step(0, lever.pos, value))

    def capture(self) -> None:
        """A appeler apres chaque tick, ou apres chaque action utilisateur."""
        tick = max(0, self.sim.state.tick - self.start)
        for pos, value in self.sim.state.commands.items():
            value = int(value)
            if self._last.get(pos) != value:
                self._last[pos] = value
                self.steps.append(Step(tick, pos, value))

    def scenario(self, nom: str, vaisseau: str, **kwargs) -> Scenario:
        ticks = max([s.tick for s in self.steps] + [0])
        ticks = max(ticks, self.sim.state.tick - self.start)
        kwargs.setdefault("editions", _editions_of(self.sim.model))
        return Scenario(nom=nom, vaisseau=vaisseau, ticks=max(ticks, 1),
                        options=replace(self.sim.options),
                        commandes=tuple(self.steps), **kwargs)


def library(directory: str | Path | None = None) -> list[Scenario]:
    """La bibliotheque de reference, triee par nom de fichier."""
    directory = Path(directory) if directory else default_library()
    if not directory.is_dir():
        return []
    return [Scenario.load(p) for p in sorted(directory.glob("*.json"))]
