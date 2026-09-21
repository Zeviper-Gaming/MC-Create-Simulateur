"""Configuration de l'utilisateur : fichiers recents, dernier dossier, journal.

Sans Qt, sans registre : un fichier JSON lisible a la main, comme le cahier le
demande pour tout ce que l'outil ecrit. Rien ici ne touche au systeme — pas
d'association de fichier, pas de cle de registre.

Ou vit-il :

    Windows   %LOCALAPPDATA%\\createsim
    macOS     ~/Library/Application Support/createsim
    Linux     $XDG_CONFIG_HOME/createsim  (ou ~/.config/createsim)

`CREATESIM_HOME` remplace tout cela — c'est ce qui permet aux tests, et a
quelqu'un qui veut une installation portable, de garder la configuration a cote
du programme.

Ce module sait aussi ou Create range ses fichiers. Un `.nbt` de vaisseau vit
dans le dossier `schematics` d'une instance Minecraft, et c'est la que
l'utilisateur voudra aller le chercher : le lui proposer evite un parcours
d'arborescence a chaque ouverture.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP = "createsim"
MAX_RECENT = 10
SETTINGS_NAME = "reglages.json"
LOG_NAME = "createsim.log"
LOG_LIMIT = 512 * 1024


def user_dir() -> Path:
    """Le dossier de configuration de l'utilisateur (non cree)."""
    override = os.environ.get("CREATESIM_HOME")
    if override:
        return Path(override)
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return base / APP


def log_path() -> Path:
    return user_dir() / LOG_NAME


# ---------------------------------------------------------------------------
def schematics_dirs() -> list[Path]:
    """Les dossiers `schematics` d'instances Minecraft, ceux qui existent.

    Ordre : `CREATESIM_SCHEMATICS` (separe par le separateur de chemins du
    systeme), puis CurseForge, puis Prism / MultiMC, puis le lanceur officiel.
    Un dossier absent est ignore, jamais signale : l'utilisateur n'a qu'un seul
    de ces lanceurs.
    """
    home = Path.home()
    roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    found: list[Path] = []

    for raw in (os.environ.get("CREATESIM_SCHEMATICS") or "").split(os.pathsep):
        if raw.strip():
            found.append(Path(raw.strip()))

    patterns = [
        (home, "curseforge/minecraft/Instances/*/schematics"),
        (roaming, "PrismLauncher/instances/*/minecraft/schematics"),
        (roaming, "PrismLauncher/instances/*/.minecraft/schematics"),
        (home / ".local/share", "PrismLauncher/instances/*/minecraft/schematics"),
        (roaming, ".minecraft/schematics"),
        (home, ".minecraft/schematics"),
        (home, "Library/Application Support/minecraft/schematics"),
    ]
    for base, pattern in patterns:
        try:
            found.extend(sorted(base.glob(pattern)))
        except (OSError, ValueError):
            continue

    out: list[Path] = []
    seen: set[str] = set()
    for path in found:
        try:
            key = str(path.resolve()).lower()
            if key in seen or not path.is_dir():
                continue
        except OSError:
            continue
        seen.add(key)
        out.append(path)
    return out


def nbt_files(directory: Path, limit: int = 60) -> list[Path]:
    """Les `.nbt` d'un dossier, les plus recents d'abord.

    Un seul niveau : `schematics/uploaded/` recoit les copies que Create depose
    en multijoueur, et les lister doublerait chaque vaisseau.
    """
    try:
        files = [p for p in directory.iterdir()
                 if p.is_file() and p.suffix.lower() == ".nbt"]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


# ---------------------------------------------------------------------------
@dataclass
class Settings:
    """Ce dont l'outil se souvient d'une fois sur l'autre."""

    recent: list[str] = field(default_factory=list)
    last_dir: str | None = None
    #: de ou vient le fichier, pour ne pas ecrire hors de la ou il est lu
    path: Path | None = field(default=None, repr=False, compare=False)

    # -- fichier -----------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """Lit les reglages. Un fichier absent ou abime donne des reglages
        vides : perdre la liste des recents ne doit jamais empecher de lancer."""
        path = Path(path) if path else user_dir() / SETTINGS_NAME
        settings = cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            recent = raw.get("recent", [])
            if isinstance(recent, list):
                settings.recent = [str(p) for p in recent if isinstance(p, str)]
            last = raw.get("dernier_dossier")
            settings.last_dir = str(last) if isinstance(last, str) else None
        except (OSError, ValueError, AttributeError):
            pass
        return settings

    def save(self) -> bool:
        """Ecrit les reglages. `False` si le disque refuse : une session sans
        memoire vaut mieux qu'une session qui plante a la fermeture."""
        path = self.path or user_dir() / SETTINGS_NAME
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(
                {"recent": self.recent, "dernier_dossier": self.last_dir},
                ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            return True
        except OSError:
            return False

    # -- recents -----------------------------------------------------------
    def add_recent(self, path: str | Path) -> None:
        """Place un fichier en tete de liste, sans doublon, et retient son dossier."""
        path = Path(path)
        try:
            text = str(path.resolve())
        except OSError:
            text = str(path)
        key = text.lower() if sys.platform == "win32" else text
        self.recent = [text] + [
            p for p in self.recent
            if (p.lower() if sys.platform == "win32" else p) != key]
        del self.recent[MAX_RECENT:]
        self.last_dir = str(path.parent)

    def recent_existing(self) -> list[Path]:
        """Les recents qui existent encore : un fichier deplace disparait de la
        liste au lieu d'y rester comme un piege."""
        return [Path(p) for p in self.recent if Path(p).is_file()]

    def start_dir(self) -> str:
        """Le dossier ou ouvrir la boite de dialogue."""
        if self.last_dir and Path(self.last_dir).is_dir():
            return self.last_dir
        found = schematics_dirs()
        if found:
            return str(found[0])
        return str(Path.home())


# ---------------------------------------------------------------------------
def prepare_streams() -> Path | None:
    """Dans un executable sans console, `sys.stdout` vaut `None` : le moindre
    `print` leve alors une exception. On le redirige vers le journal.

    Renvoie le chemin du journal quand la redirection a eu lieu.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > LOG_LIMIT:
            path.replace(path.with_suffix(".log.1"))
        stream = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
        path = None
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return path
