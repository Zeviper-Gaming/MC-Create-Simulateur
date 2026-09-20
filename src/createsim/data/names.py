"""Noms donnes aux organes par l'utilisateur.

Un vaisseau reel porte une douzaine de leviers, et « create:analog_lever
(14, 13, 20) » ne dit rien de ce qu'il fait. Pouvoir ecrire « ballast avant »
transforme un tableau de coordonnees en planche de bord.

Les noms vivent a cote du fichier de structure, dans un `.noms.json`, jamais
dedans : le `.nbt` d'origine n'est JAMAIS ecrit. Un nom absent retombe sur le
libelle par defaut, et le format reste lisible a la main.
"""
from __future__ import annotations

import json
from pathlib import Path

SUFFIX = ".noms.json"


def key_for(kind: str, identifier) -> str:
    """Clef stable d'un organe : son genre et sa position dans la structure."""
    if isinstance(identifier, (tuple, list)):
        identifier = ",".join(str(int(v)) for v in identifier)
    return "%s:%s" % (kind, identifier)


class Names:
    """Table nom-par-organe, chargee et enregistree a cote du vaisseau."""

    def __init__(self, path: Path | None = None, entries: dict | None = None):
        self.path = Path(path) if path else None
        self.entries: dict[str, str] = dict(entries or {})

    # -- persistance -------------------------------------------------------
    @classmethod
    def for_structure(cls, structure_path: str | None) -> "Names":
        if not structure_path:
            return cls()
        path = Path(structure_path).with_suffix(SUFFIX)
        entries = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    entries = {str(k): str(v) for k, v in loaded.items()}
            except (OSError, ValueError):
                entries = {}
        return cls(path, entries)

    def save(self) -> bool:
        """Ecrit le fichier de noms. Le `.nbt` d'origine n'est pas touche."""
        if self.path is None:
            return False
        try:
            if self.entries:
                self.path.write_text(
                    json.dumps(dict(sorted(self.entries.items())), indent=1,
                               ensure_ascii=False),
                    encoding="utf-8")
            elif self.path.is_file():
                self.path.unlink()
            return True
        except OSError:
            return False

    # -- lecture et ecriture ----------------------------------------------
    def get(self, kind: str, identifier, default: str = "") -> str:
        return self.entries.get(key_for(kind, identifier), default)

    def has(self, kind: str, identifier) -> bool:
        return key_for(kind, identifier) in self.entries

    def set(self, kind: str, identifier, name: str) -> None:
        key = key_for(kind, identifier)
        name = (name or "").strip()
        if name:
            self.entries[key] = name
        else:
            self.entries.pop(key, None)
        self.save()

    def label(self, kind: str, identifier, default: str) -> str:
        """Le nom donne s'il existe, sinon le libelle par defaut."""
        return self.get(kind, identifier) or default

    def describe(self, kind: str, identifier, default: str) -> str:
        """Le nom donne suivi du libelle technique, pour ne pas perdre l'un.

        Un rapport doit rester rapprochable du fichier : « ballast avant
        (14, 13, 20) » se retrouve en jeu, « ballast avant » seul non.
        """
        given = self.get(kind, identifier)
        return "%s (%s)" % (given, default) if given else default

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)
