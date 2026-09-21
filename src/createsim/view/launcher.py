"""Le lanceur : ouvrir un `.nbt` par n'importe quel chemin.

Il y en a quatre, et tous passent par `Launcher.open` :

    la ligne de commande     createsim vaisseau.nbt        (et l'executable)
    glisser-deposer          sur la fenetre, ou sur l'icone de l'executable
    la boite de dialogue     Fichier > Ouvrir, Ctrl+O
    l'accueil                recents, schematics de vos instances, exemples

Un seul vaisseau est ouvert a la fois : le cahier tranche le multi-vaisseaux, la
comparaison passe par la superposition de deux executions, pas par deux
vehicules dans une scene. Ouvrir un fichier remplace donc la fenetre courante,
a la meme place et a la meme taille.

Ce module ne connait pas la physique. Il charge, il installe une fenetre, il se
souvient. Ce qu'il fait d'un fichier qui ne charge pas compte autant que le
reste : un `.nbt` qui n'est pas une structure est un cas normal, pas une erreur
de programmation, et il ne doit ni fermer l'outil ni afficher un `KeyError`.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import PySide6
from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__, config, paths
from ..data.nbt import StructureError
from ..data.tables import Tables
from .app import VehicleWindow, _load
from .cubes import default_format
from .welcome import Section, WelcomeWindow

DEFAULT_SIZE = (1280, 720)

_DROP = (QtCore.QEvent.Type.DragEnter, QtCore.QEvent.Type.DragMove,
         QtCore.QEvent.Type.Drop)


def nbt_paths(mime: QtCore.QMimeData) -> list[Path]:
    """Les `.nbt` d'un glisser-deposer. L'extension seule decide : on est appele
    a chaque mouvement de souris, pas le moment d'interroger le disque."""
    if not mime.hasUrls():
        return []
    out: list[Path] = []
    for url in mime.urls():
        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".nbt":
                out.append(path)
    return out


def instance_label(schematics: Path) -> str:
    """Le nom lisible d'un dossier `schematics` : celui de l'instance.

    CurseForge  Instances/<instance>/schematics
    Prism       instances/<instance>/minecraft/schematics
    officiel    .minecraft/schematics
    """
    parent = schematics.parent
    if parent.name.lower() in ("minecraft", ".minecraft"):
        if parent.parent.parent.name.lower() == "instances":
            return parent.parent.name
        return "Minecraft"
    return parent.name or str(schematics)


class Launcher(QtCore.QObject):
    """Possede la fenetre courante et sait la remplacer."""

    def __init__(self, app: QtWidgets.QApplication, tables: Tables,
                 settings: config.Settings, size: tuple[int, int] = DEFAULT_SIZE,
                 verbose: bool = False, interactive: bool = True):
        super().__init__(app)
        self.app = app
        self.tables = tables
        self.settings = settings
        self.size = size
        self.verbose = verbose
        #: faux en `--bench` / `--capture` : une boite de dialogue y bloquerait
        #: un script qui n'a personne pour la fermer
        self.interactive = interactive
        #: un lancement de test ne doit pas laisser sa trace dans les recents
        self.remember = interactive
        self.window: VehicleWindow | None = None
        self.welcome: WelcomeWindow | None = None
        self.last_error: str | None = None
        self.load_seconds = 0.0
        app.installEventFilter(self)

    # -- demarrage ----------------------------------------------------------
    def start(self, files) -> None:
        """Ouvre le premier fichier donne, sinon l'accueil.

        Si le fichier ne charge pas, l'accueil s'ouvre quand meme : sortir
        juste apres avoir affiche l'erreur laisserait l'utilisateur devant rien.
        """
        files = [Path(f) for f in files]
        if files and self.open(files[0]):
            self._note_ignored(len(files) - 1)
            return
        self.show_welcome()

    # -- ouvrir -------------------------------------------------------------
    def open(self, path) -> bool:
        """Charge `path` et remplace la fenetre courante. `False` si ca echoue,
        auquel cas rien n'a change."""
        path = Path(path)
        if not path.is_file():
            return self._fail("Fichier introuvable",
                              "%s n'existe pas ou n'est pas un fichier." % path)
        begin = time.perf_counter()
        error: tuple[str, str] | None = None
        self.app.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            model, sim = _load(str(path), self.tables)
            window = VehicleWindow(model, sim)
        except StructureError as exc:
            error = ("Ce fichier n'est pas un vaisseau lisible", str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            error = ("Impossible d'ouvrir %s" % path.name,
                     "%s : %s\n\nLe détail est dans le journal :\n%s"
                     % (type(exc).__name__, exc, config.log_path()))
        finally:
            self.app.restoreOverrideCursor()
        # hors du `try` : la boite d'erreur ne doit pas s'ouvrir sous un curseur
        # d'attente qui ne se leve qu'apres elle
        if error is not None:
            return self._fail(*error)
        self.load_seconds = time.perf_counter() - begin
        self.last_error = None
        self._install(window, path)
        return True

    def open_many(self, paths) -> bool:
        """Un seul vaisseau a la fois : ouvre le premier, dit ce qu'il laisse."""
        paths = [Path(p) for p in paths]
        if not paths:
            return False
        ok = self.open(paths[0])
        if ok:
            self._note_ignored(len(paths) - 1)
        return ok

    def browse(self) -> None:
        chosen = self.pick_file()
        if chosen:
            self.open(chosen)

    def pick_file(self) -> str | None:
        """La boite de dialogue. Separee pour que les tests la remplacent."""
        chosen, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self.window or self.welcome, "Ouvrir un vaisseau",
            self.settings.start_dir(),
            "Structures Minecraft (*.nbt);;Tous les fichiers (*)")
        return chosen or None

    # -- fenetres -----------------------------------------------------------
    def _install(self, window: VehicleWindow, path: Path) -> None:
        old = self.window
        if self.remember:
            self.settings.add_recent(path)
            self.settings.save()

        self._connect(window)
        if old is not None:
            # meme place, meme taille, meme etat maximise
            window.restoreGeometry(old.saveGeometry())
        else:
            window.resize(*self.size)
        window.show()
        if self.verbose:
            self._describe(window)

        # L'ancienne fenetre ferme APRES l'affichage de la nouvelle : fermer la
        # derniere fenetre visible ferait quitter l'application.
        for stale in (old, self.welcome):
            if stale is not None:
                stale.close()
                stale.deleteLater()
        self.welcome = None
        self.window = window
        self._refresh_recent()

    def show_welcome(self) -> None:
        if self.welcome is None:
            self.welcome = WelcomeWindow()
            self._connect(self.welcome)
        self.welcome.set_sections(self.sections())
        self._refresh_recent()
        self.welcome.show()
        self.welcome.raise_()
        self.welcome.activateWindow()

    def _connect(self, window) -> None:
        window.open_requested.connect(self.open)
        window.browse_requested.connect(self.browse)
        window.about_requested.connect(self.about)

    def _refresh_recent(self) -> None:
        recent = self.settings.recent_existing()
        for window in (self.window, self.welcome):
            if window is not None:
                window.set_recent(recent)

    def sections(self) -> list[Section]:
        """Ce que l'accueil propose, dans l'ordre ou on en a besoin."""
        out = [Section("Ouverts récemment", self.settings.recent_existing(),
                       with_folder=True)]
        for folder in config.schematics_dirs():
            out.append(Section("Vos schematics — %s" % instance_label(folder),
                               config.nbt_files(folder)))
        examples = paths.examples_dir()
        if examples is not None:
            out.append(Section("Exemples fournis", sorted(examples.glob("*.nbt"))))
        return out

    # -- messages -----------------------------------------------------------
    def _fail(self, title: str, message: str) -> bool:
        self.last_error = "%s — %s" % (title, message)
        self.report_error(title, message)
        return False

    def report_error(self, title: str, message: str) -> None:
        """Dit une erreur a l'utilisateur. Separee pour que les tests la captent
        au lieu d'ouvrir une boite modale."""
        if not self.interactive:
            print("%s : %s" % (title, message), file=sys.stderr)
            return
        QtWidgets.QMessageBox.warning(self.window or self.welcome, title, message)

    def _note_ignored(self, count: int) -> None:
        if count > 0 and self.window is not None:
            self.window.statusBar().showMessage(
                "un seul vaisseau à la fois : %d autre(s) fichier(s) ignoré(s)"
                % count, 8000)

    def about(self) -> None:
        manifest = self.tables.manifest or {}
        mods = ", ".join("%s %s" % (name, info.get("version", "?"))
                         for name, info in (manifest.get("mods") or {}).items())
        html = (
            "<h3>createsim %s</h3>"
            "<p>Banc d'essai hors-jeu pour véhicules Create.</p>"
            "<p>Constantes issues de : <b>%s</b><br>"
            "Minecraft %s · %s</p>"
            "<p style='color:gray'>Python %s · PySide6 %s · Qt %s<br>"
            "%s<br>Réglages : %s<br>Journal : %s</p>"
            % (__version__, mods or "?", manifest.get("minecraft", "?"),
               manifest.get("loader", "?"),
               sys.version.split()[0], PySide6.__version__, QtCore.qVersion(),
               "exécutable autonome" if paths.frozen() else "depuis les sources",
               self.settings.path or config.user_dir(), config.log_path()))
        QtWidgets.QMessageBox.about(self.window or self.welcome,
                                    "À propos de createsim", html)

    # -- glisser-deposer ----------------------------------------------------
    def eventFilter(self, obj, event) -> bool:                    # noqa: N802
        """Accepte un `.nbt` lache n'importe ou dans l'application.

        Au niveau de l'application et non de chaque fenetre : un champ de saisie
        — il y en a partout dans le bandeau — accepte les depots par defaut et,
        n'y comprenant pas un fichier, le refuserait, coupant la route a la
        fenetre qui le contient.
        """
        kind = event.type()
        if kind not in _DROP:
            return False
        files = nbt_paths(event.mimeData())
        if not files:
            return False
        event.acceptProposedAction()
        if kind == QtCore.QEvent.Type.Drop:
            # Ouvrir ICI bloquerait l'explorateur qui tient le glisser, et
            # detruirait la fenetre dont on est en train de traiter l'evenement.
            QtCore.QTimer.singleShot(0, lambda f=files: self.open_many(f))
        return True

    # -- modes de diagnostic ------------------------------------------------
    def bench(self, seconds: float) -> int:
        """Mesure la cadence de la boucle complete, simulation ET rendu."""
        window = self.window
        if window is None:
            print("--bench demande un fichier .nbt valide", file=sys.stderr)
            return 2
        for _ in range(10):
            window.view.update()
            self.app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
        begin = time.perf_counter()
        frames = 0
        while time.perf_counter() < begin + seconds:
            window._advance()
            self.app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
            frames += 1
        elapsed = time.perf_counter() - begin
        rate = frames / elapsed if elapsed else 0.0
        print("boucle      : %.0f tours/s sur %.1f s (%d tours, %dx%d)"
              % (rate, elapsed, frames, window.width(), window.height()))
        print("NF1 (20 ticks/s obligatoire) : %s"
              % ("TENU" if rate >= 20 else "NON TENU"))
        window.close()
        return 0 if rate >= 20 else 1

    def capture(self, png: str, settle: float = 1.5) -> int:
        """Enregistre la fenetre courante dans `png`, puis sort.

        Elle ne photographie que la fenetre de l'application — pas l'ecran. Sert
        a verifier qu'un executable construit affiche bien ce qu'il doit, en
        particulier la vue 3D, la partie qu'un paquet casse le plus volontiers.
        """
        target = self.window or self.welcome
        if target is None:
            return 2
        deadline = time.perf_counter() + settle
        while time.perf_counter() < deadline:
            self.app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
        image = target.grab()
        Path(png).parent.mkdir(parents=True, exist_ok=True)
        saved = image.save(str(png))
        target.close()
        ok = saved and Path(png).is_file() and Path(png).stat().st_size > 0
        print("capture     : %s (%dx%d) %s"
              % (png, image.width(), image.height(), "OK" if ok else "ECHEC"))
        return 0 if ok else 1

    def _describe(self, window: VehicleWindow) -> None:
        stats = window.mesh.stats()
        print("maillage    : %d blocs -> %d quadrilateres (%.1f %% fusionnes), "
              "%d triangles"
              % (stats["blocs"], stats["quadrilateres"],
                 stats["reduction_par_fusion"] * 100, stats["triangles"]))
        drawn = sum(e["dessinees"] for e in window.overlay_data.legend)
        print("forces      : %d vecteurs, echelle 1 bloc = %.0f"
              % (drawn, (1.0 / window.overlay_data.scale)
                 if window.overlay_data.scale else 0))
        redstone = window.model.organ("redstone")
        print("commandes   : %d levier(s), %d consommateur(s)"
              % (len(redstone.levers), len(redstone.consumers)))
        print("chargement  : %.2f s" % self.load_seconds)


# ---------------------------------------------------------------------------
def install_excepthook(launcher: Launcher) -> None:
    """Une exception dans un slot Qt n'arrete pas l'application : elle s'imprime
    et on continue. Dans un executable sans console, elle disparaitrait sans
    laisser de trace. On la journalise et on la dit — une fois, pas cent : une
    erreur dans un minuteur se repete vingt fois par seconde."""
    previous = sys.excepthook
    state = {"busy": False, "last": 0.0}

    def hook(kind, value, tb) -> None:
        if issubclass(kind, KeyboardInterrupt):
            previous(kind, value, tb)
            return
        text = "".join(traceback.format_exception(kind, value, tb))
        try:
            sys.stderr.write(text)
        except Exception:                                         # noqa: BLE001
            pass
        if (state["busy"] or not launcher.interactive
                or time.monotonic() - state["last"] < 3.0):
            return
        state["busy"] = True
        try:
            launcher.report_error(
                "Erreur inattendue",
                "%s : %s\n\nLe détail est dans le journal :\n%s"
                % (kind.__name__, value, config.log_path()))
        finally:
            state["busy"] = False
            state["last"] = time.monotonic()

    sys.excepthook = hook


def prepare_app(app: QtWidgets.QApplication) -> None:
    app.setApplicationName("createsim")
    app.setApplicationVersion(__version__)
    icon = paths.asset("createsim.png")
    if icon is not None:
        app.setWindowIcon(QtGui.QIcon(str(icon)))


def run(files=(), tables: Tables | None = None, bench_seconds: float = 0.0,
        capture: str | None = None, width: int = DEFAULT_SIZE[0],
        height: int = DEFAULT_SIZE[1], settings: config.Settings | None = None,
        verbose: bool = False) -> int:
    """Lance l'application. Avec `bench_seconds` ou `capture`, mesure ou
    photographie puis sort."""
    QtGui.QSurfaceFormat.setDefaultFormat(default_format())
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    prepare_app(app)

    scripted = bool(bench_seconds or capture)
    launcher = Launcher(app, tables or Tables.load(), settings or config.Settings.load(),
                        (width, height), verbose=verbose or bool(bench_seconds),
                        interactive=not scripted)
    install_excepthook(launcher)
    launcher.start(files)
    if bench_seconds:
        return launcher.bench(bench_seconds)
    if capture:
        return launcher.capture(capture)
    return app.exec()
