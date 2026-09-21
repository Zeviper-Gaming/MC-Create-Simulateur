"""La fenetre d'accueil : ce qu'on voit quand on lance l'outil sans fichier.

Double-cliquer sur l'executable ne donne aucun chemin. Une fenetre vide serait
un cul-de-sac ; une boite de dialogue de fichier immediate, abrupte. L'accueil
propose ce qu'on ouvre le plus souvent, dans l'ordre ou on en a besoin :

    les fichiers ouverts recemment
    les .nbt des dossiers `schematics` de vos instances Minecraft
    les vaisseaux d'exemple livres avec l'outil

et laisse toujours la porte ouverte : Ouvrir…, ou glisser un fichier dessus.

La fenetre ne charge rien. Elle emet `open_requested` avec un chemin, et c'est
le lanceur qui ouvre — ce qui la garde testable sans vaisseau.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__
from .menus import fill_recent, install_menus

ACCENT = "#78c8ff"
#: fichiers listes par section : au-dela, la boite de dialogue fait mieux
PER_SECTION = 12


def describe(path: Path, with_folder: bool) -> str:
    """La seconde ligne d'un fichier : taille, date, et dossier si utile."""
    try:
        stat = path.stat()
    except OSError:
        return "introuvable"
    size = stat.st_size
    text = "%.0f Ko" % (size / 1024) if size >= 1024 else "%d o" % size
    text += " · %s" % datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")
    if with_folder:
        text += " · %s" % path.parent
    return text


class Section:
    """Un groupe de fichiers sous un titre."""

    __slots__ = ("title", "files", "with_folder")

    def __init__(self, title: str, files: list[Path], with_folder: bool = False):
        self.title = title
        self.files = list(files)[:PER_SECTION]
        self.with_folder = with_folder


class WelcomeWindow(QtWidgets.QMainWindow):
    open_requested = QtCore.Signal(str)
    browse_requested = QtCore.Signal()
    about_requested = QtCore.Signal()

    def __init__(self, sections: list[Section] | None = None):
        super().__init__()
        self.setWindowTitle("createsim")
        self.resize(780, 640)
        self._recent_menu = install_menus(self)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(30, 26, 30, 22)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("createsim")
        title.setStyleSheet("font-size: 30px; font-weight: bold; color: %s;" % ACCENT)
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "Banc d'essai hors-jeu pour véhicules Create — "
            "non pas ce que le véhicule fait, mais <b>quelle force en est responsable</b>.")
        subtitle.setWordWrap(True)
        subtitle.setTextFormat(QtCore.Qt.TextFormat.RichText)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        row = QtWidgets.QHBoxLayout()
        self.browse = QtWidgets.QPushButton("Ouvrir un fichier .nbt…")
        self.browse.setDefault(True)
        self.browse.setMinimumHeight(34)
        self.browse.setMinimumWidth(220)
        self.browse.clicked.connect(self.browse_requested.emit)
        row.addWidget(self.browse)
        hint = QtWidgets.QLabel("Ctrl+O")
        hint.setEnabled(False)
        row.addWidget(hint)
        row.addStretch(1)
        layout.addLayout(row)

        self.list = QtWidgets.QListWidget()
        self.list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.list.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setSpacing(1)
        self.list.itemActivated.connect(self._activated)
        layout.addWidget(self.list, 1)

        self.drop = QtWidgets.QLabel("… ou glissez un fichier .nbt n'importe où dans cette fenêtre")
        self.drop.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.drop.setMinimumHeight(54)
        self.drop.setStyleSheet(
            "QLabel { border: 2px dashed palette(mid); border-radius: 8px;"
            " color: palette(placeholder-text); }")
        layout.addWidget(self.drop)

        version = QtWidgets.QLabel("version %s" % __version__)
        version.setEnabled(False)
        version.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addWidget(version)

        self.setCentralWidget(central)
        self.set_sections(sections or [])

    # -- contenu ------------------------------------------------------------
    def set_recent(self, paths) -> None:
        fill_recent(self, self._recent_menu, list(paths))

    def set_sections(self, sections: list[Section]) -> None:
        self.list.clear()
        self.sections = list(sections)
        dim = self.palette().color(QtGui.QPalette.ColorRole.PlaceholderText).name()
        shown = 0
        for section in self.sections:
            if not section.files:
                continue
            self._header(section.title, dim)
            for path in section.files:
                self._file(path, section.with_folder, dim)
                shown += 1
        if not shown:
            item = QtWidgets.QListWidgetItem(
                "Aucun vaisseau à proposer. Ouvrez un fichier .nbt, "
                "ou glissez-le ici.")
            item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        else:
            first = next((self.list.item(i) for i in range(self.list.count())
                          if self.list.item(i).data(QtCore.Qt.ItemDataRole.UserRole)),
                         None)
            if first is not None:
                self.list.setCurrentItem(first)

    def _header(self, title: str, dim: str) -> None:
        item = QtWidgets.QListWidgetItem()
        item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
        label = QtWidgets.QLabel(
            "<span style='color:%s; font-weight:bold; letter-spacing:1px;'>%s</span>"
            % (ACCENT, title.upper()))
        label.setContentsMargins(4, 12, 0, 4)
        label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        item.setSizeHint(label.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, label)

    def _file(self, path: Path, with_folder: bool, dim: str) -> None:
        item = QtWidgets.QListWidgetItem()
        item.setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
        item.setToolTip(str(path))
        label = QtWidgets.QLabel(
            "<b>%s</b><br><span style='color:%s;'>%s</span>"
            % (path.name, dim, describe(path, with_folder).replace("<", "&lt;")))
        label.setContentsMargins(10, 4, 0, 4)
        label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        item.setSizeHint(label.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, label)

    def file_items(self) -> list[str]:
        """Les chemins listes, dans l'ordre d'affichage."""
        out = []
        for i in range(self.list.count()):
            path = self.list.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
            if path:
                out.append(path)
        return out

    def _activated(self, item: QtWidgets.QListWidgetItem) -> None:
        path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if path:
            self.open_requested.emit(path)
