"""Chargement des tables de constantes.

Chaque valeur porte le fichier source dont elle vient : la tracabilite est une
donnee, pas un commentaire. Une grandeur non extraite du code est signalee
comme telle plutot qu'estimee.

Mode expert (F1) : les constantes restent modifiables, mais derriere un
interrupteur qui se coupe. Le couper restaure les valeurs sourcees sans
redemarrage. Tant qu'il est actif, toute grandeur calculee porte une marque
disant qu'elle ne repose plus sur les constantes du jeu.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TABLE_NAMES = ("masses", "pressure", "forces", "kinetics", "stress")


class TableError(RuntimeError):
    pass


def find_tables_dir(start: Path | None = None) -> Path:
    """Remonte depuis le paquet jusqu'au dossier data/tables du depot.

    Sans `start`, la racine des ressources vient de `createsim.paths` : c'est
    la meme dans un depot et dans un executable PyInstaller.
    """
    if start is None:
        from .. import paths
        try:
            candidate = paths.data_dir() / "tables"
            if (candidate / "manifest.json").is_file():
                return candidate
        except FileNotFoundError:
            pass
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "tables"
        if (candidate / "manifest.json").is_file():
            return candidate
    raise TableError(
        "data/tables/manifest.json introuvable en remontant depuis %s" % here)


@dataclass(frozen=True)
class Entry:
    """Une constante et sa provenance."""

    key: str
    value: Any
    source: str
    mod: str
    note: str | None = None

    @property
    def qualified(self) -> str:
        return self.key


@dataclass
class Tables:
    """Les tables chargees, plus la couche d'overrides du mode expert."""

    directory: Path
    manifest: dict
    entries: dict[str, Entry] = field(default_factory=dict)
    _overrides: dict[str, Any] = field(default_factory=dict, repr=False)
    _expert: bool = field(default=False, repr=False)
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    # -- chargement --------------------------------------------------------
    @classmethod
    def load(cls, directory: Path | str | None = None) -> "Tables":
        d = Path(directory) if directory else find_tables_dir()
        if not d.is_dir():
            raise TableError("dossier de tables introuvable : %s" % d)
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        entries: dict[str, Entry] = {}
        for name in TABLE_NAMES:
            path = d / (name + ".json")
            if not path.is_file():
                raise TableError("table manquante : %s" % path)
            doc = json.loads(path.read_text(encoding="utf-8"))
            for key, raw in doc["entries"].items():
                qualified = "%s.%s" % (name, key)
                entries[qualified] = Entry(
                    key=qualified, value=raw["value"], source=raw["source"],
                    mod=raw["mod"], note=raw.get("note"))
        return cls(directory=d, manifest=manifest, entries=entries)

    # -- lecture -----------------------------------------------------------
    def get(self, qualified: str) -> Any:
        if self._expert and qualified in self._overrides:
            return self._overrides[qualified]
        try:
            return self.entries[qualified].value
        except KeyError:
            raise TableError("constante inconnue : %s" % qualified) from None

    def entry(self, qualified: str) -> Entry:
        try:
            return self.entries[qualified]
        except KeyError:
            raise TableError("constante inconnue : %s" % qualified) from None

    def source_of(self, qualified: str) -> str:
        """Le fichier d'ou vient la valeur — affichable a la demande."""
        if self._expert and qualified in self._overrides:
            return "MODE EXPERT (valeur saisie a la main, hors constantes du jeu)"
        return self.entry(qualified).source

    def cached_set(self, qualified: str) -> frozenset:
        key = "set:" + qualified
        got = self._cache.get(key)
        if got is None:
            got = frozenset(self.get(qualified))
            self._cache[key] = got
        return got

    # -- mode expert -------------------------------------------------------
    @property
    def expert_mode(self) -> bool:
        return self._expert

    @expert_mode.setter
    def expert_mode(self, on: bool) -> None:
        self._expert = bool(on)
        self._cache.clear()

    def override(self, qualified: str, value: Any) -> None:
        """Ecrase une constante. Exige le mode expert."""
        if qualified not in self.entries:
            raise TableError("constante inconnue : %s" % qualified)
        if not self._expert:
            raise TableError(
                "mode expert desactive : %s reste a sa valeur sourcee" % qualified)
        self._overrides[qualified] = value
        self._cache.clear()

    def clear_overrides(self) -> None:
        """Restaure les valeurs sourcees, sans redemarrage."""
        self._overrides.clear()
        self._cache.clear()

    @property
    def tainted(self) -> bool:
        """Vrai si une grandeur calculee ne repose plus sur les constantes du jeu."""
        return bool(self._expert and self._overrides)

    @property
    def tainted_keys(self) -> list[str]:
        return sorted(self._overrides) if self._expert else []

    def provenance(self) -> dict:
        """Bloc de tracabilite a joindre a tout rapport."""
        out = {
            "mods": self.manifest.get("mods", {}),
            "extraction": self.manifest.get("extracted"),
            "mode_expert": self._expert,
            "valeurs_modifiees": self.tainted_keys,
        }
        if self.tainted:
            out["avertissement"] = (
                "MODE EXPERT ACTIF : les grandeurs ci-dessous ne reposent plus "
                "entierement sur les constantes du jeu.")
        return out


class BlockProperties:
    """Resolution nom de bloc -> propriete physique, d'apres les tables.

    Pure consultation de tables : l'ordre des regles reproduit exactement celui
    des datapacks Sable (les priorites de tags), sans aucun calcul physique.
    """

    def __init__(self, tables: Tables):
        self.t = tables
        self._mass_cache: dict[str, float] = {}

    # -- masses ------------------------------------------------------------
    def mass(self, name: str) -> float:
        got = self._mass_cache.get(name)
        if got is None:
            got = self._resolve_mass(name)
            self._mass_cache[name] = got
        return got

    def _resolve_mass(self, name: str) -> float:
        t = self.t
        g = t.get
        if name in t.cached_set("masses.no_collision_blocks"):
            return g("masses.no_collision")
        if name in t.cached_set("masses.envelope_blocks"):
            return g("masses.super_light")
        if name in t.cached_set("masses.exact_weightless"):
            return g("masses.weightless")
        if name in t.cached_set("masses.exact_super_light"):
            return g("masses.super_light")
        if name in t.cached_set("masses.sail_blocks"):
            return g("masses.super_light")
        if name.endswith(tuple(g("masses.suffix_super_light"))):
            return g("masses.super_light")
        if name.endswith(("_stairs", "_slab")):
            wood = any(w in name for w in g("masses.wood_keywords"))
            return g("masses.super_light") if wood else g("masses.light")
        if name in t.cached_set("masses.exact_light"):
            return g("masses.light")
        if name.endswith(tuple(g("masses.wood_suffixes"))):
            return g("masses.light")
        if name == "minecraft:bedrock":
            return g("masses.bedrock")
        if name == "create:flywheel":
            return g("masses.flywheel")
        if name in t.cached_set("masses.exact_super_heavy_removed"):
            return g("masses.default")
        if any(k in name for k in g("masses.super_heavy_keywords")):
            return g("masses.super_heavy")
        if any(k in name for k in g("masses.heavy_keywords")):
            return g("masses.heavy")
        return g("masses.default")

    # -- familles ----------------------------------------------------------
    def is_airtight(self, name: str) -> bool:
        return name in self.t.cached_set("masses.airtight_blocks")

    def is_sail(self, name: str) -> bool:
        return name in self.t.cached_set("masses.sail_blocks")

    def is_levitite(self, name: str) -> bool:
        return name in self.t.cached_set("forces.levitite_blocks")

    def is_wheel_mount(self, name: str) -> bool:
        return name in self.t.cached_set("forces.wheel_mount_blocks")

    def is_known_namespace(self, name: str) -> bool:
        return name.split(":")[0] in self.t.cached_set("masses.known_namespaces")

    def has_collision(self, name: str) -> bool:
        return (name not in self.t.cached_set("masses.no_collision_blocks")
                and not name.endswith(("_sign", "_banner")))

    # -- valeurs ponctuelles ----------------------------------------------
    def tire_radius(self, name: str | None) -> float:
        radii = self.t.get("forces.tire_radii")
        if name:
            for key, r in radii.items():
                if name.endswith(key):
                    return r
        return 1.0

    def ground_friction(self, name: str) -> float:
        return self.t.get("forces.ground_friction").get(
            name, self.t.get("forces.default_friction"))

    def stress_impact(self, name: str) -> float:
        return self.t.get("stress.impact").get(name, 0.0)

    def stress_capacity(self, name: str) -> float:
        return self.t.get("stress.capacity").get(name, 0.0)
