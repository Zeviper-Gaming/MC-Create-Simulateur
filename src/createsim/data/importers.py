"""Import des fichiers de configuration des mods vers les tables du depot.

Le cahier l'exige : le logiciel doit pouvoir se mettre a jour depuis un
`create-server.toml` ou un datapack, sans recompilation. Create Aeronautics est
en alpha ; ces valeurs bougeront.

Le schema vise est celui de Create et de ses addons :

    [kinetics.stressValues.v2.impact]
        mechanical_mixer = 4.0
    [kinetics.stressValues.v2.capacity]
        water_wheel = 32.0

Les identifiants y sont nus : l'espace de noms vient du nom du fichier.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# nom de fichier -> espace de noms des blocs qu'il configure
NAMESPACE_BY_PREFIX = {
    "create": "create",
    "aeronautics": "aeronautics",
    "simulated": "simulated",
    "offroad": "offroad",
    "sable": "sable",
    "electroenergetics": "electroenergetics",
    "createpropulsion": "createpropulsion",
    "createbigcannons": "createbigcannons",
    "createdeco": "createdeco",
}

# cle TOML -> constante des tables. Uniquement les valeurs que le noyau utilise.
SCALAR_MAP = {
    ("physics", "hotAirStrength"): "forces.hot_air_strength",
    ("physics", "steamStrength"): "forces.steam_strength",
    ("physics", "propellerBearingThrust"): "forces.propeller_bearing_thrust",
    ("physics", "propellerBearingAirflow"): "forces.propeller_bearing_airflow",
    ("physics", "woodenPropellerThrust"): "forces.wooden_propeller_thrust",
    ("kinetics", "maxRotationSpeed"): "kinetics.max_rotation_speed",
    ("kinetics", "windmillSailsPerRPM"): "kinetics.windmill_sails_per_rpm",
    ("kinetics", "minimumWindmillSails"): "kinetics.windmill_min_sails",
}


def namespace_for(path: Path) -> str:
    stem = path.stem.lower()
    for prefix, ns in NAMESPACE_BY_PREFIX.items():
        if stem.startswith(prefix):
            return ns
    return stem.split("-")[0]


def _walk(doc: dict, path: tuple[str, ...] = ()):
    for key, value in doc.items():
        here = path + (key,)
        if isinstance(value, dict):
            yield from _walk(value, here)
        else:
            yield here, value


@dataclass
class ImportResult:
    impact: dict[str, float] = field(default_factory=dict)
    capacity: dict[str, float] = field(default_factory=dict)
    scalars: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return ("%d fichiers lus, %d impacts, %d capacites, %d constantes"
                % (len(self.files), len(self.impact), len(self.capacity),
                   len(self.scalars)))


def read_configs(paths: list[Path | str]) -> ImportResult:
    """Lit des *-server.toml et en extrait ce que le noyau consomme."""
    out = ImportResult()
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            out.skipped.append("%s : introuvable" % path)
            continue
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            out.skipped.append("%s : %s" % (path, exc))
            continue
        ns = namespace_for(path)
        out.files.append(str(path))
        for keys, value in _walk(doc):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if keys[:4] == ("kinetics", "stressValues", "v2", "impact"):
                out.impact["%s:%s" % (ns, keys[4])] = float(value)
            elif keys[:4] == ("kinetics", "stressValues", "v2", "capacity"):
                out.capacity["%s:%s" % (ns, keys[4])] = float(value)
            elif len(keys) == 2 and (keys[0], keys[1]) in SCALAR_MAP:
                target = SCALAR_MAP[(keys[0], keys[1])]
                out.scalars[target] = float(value)
                out.sources[target] = "%s [%s] %s" % (path.name, keys[0], keys[1])
    return out


def diff_against(result: ImportResult, tables) -> list[dict]:
    """Ce que l'import changerait, valeur par valeur. Rien n'est ecrit ici."""
    changes: list[dict] = []
    for kind, incoming in (("impact", result.impact), ("capacity", result.capacity)):
        current = tables.get("stress." + kind)
        for block, value in sorted(incoming.items()):
            was = current.get(block)
            if was is None and value == 0.0:
                # un bloc absent des tables a deja un impact et une capacite
                # nuls : ce n'est pas un ecart, c'est la meme chose ecrite
                continue
            if was is None or abs(was - value) > 1e-9:
                changes.append({"cle": "stress.%s[%s]" % (kind, block),
                                "avant": was, "apres": value})
        for block in sorted(set(current) - set(incoming)):
            changes.append({"cle": "stress.%s[%s]" % (kind, block),
                            "avant": current[block], "apres": None,
                            "note": "absent de la config lue"})
    for key, value in sorted(result.scalars.items()):
        was = tables.get(key)
        if was is None or abs(float(was) - value) > 1e-9:
            changes.append({"cle": key, "avant": was, "apres": value})
    return changes


def _patch_json(path: Path, updates: dict[str, tuple]) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    for key, (value, source) in updates.items():
        entry = doc["entries"].setdefault(key, {"value": None, "source": "", "mod": ""})
        entry["value"] = value
        if source:
            entry["source"] = source
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")


def apply_to_tables(result: ImportResult, directory: Path) -> list[str]:
    """Ecrit les tables mises a jour. Les valeurs absentes de la config sont
    conservees : un addon desinstalle ne doit pas effacer silencieusement une
    ligne dont un vaisseau deja charge depend."""
    written: list[str] = []
    directory = Path(directory)

    if result.impact or result.capacity:
        path = directory / "stress.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        for kind, incoming in (("impact", result.impact), ("capacity", result.capacity)):
            if not incoming:
                continue
            merged = dict(doc["entries"][kind]["value"])
            for block, value in incoming.items():
                if block not in merged and value == 0.0:
                    continue        # deja nul par defaut, inutile de l'ecrire
                merged[block] = value
            doc["entries"][kind]["value"] = dict(sorted(merged.items()))
        path.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        written.append(str(path))

    by_table: dict[str, dict] = {}
    for key, value in result.scalars.items():
        table, _, leaf = key.partition(".")
        by_table.setdefault(table, {})[leaf] = (value, result.sources.get(key, ""))
    for table, updates in by_table.items():
        path = directory / (table + ".json")
        if path.is_file():
            _patch_json(path, updates)
            written.append(str(path))
    return written
