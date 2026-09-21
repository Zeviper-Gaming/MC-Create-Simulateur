"""Les menus communs aux fenetres : ouvrir, recents, quitter, a propos.

Deux fenetres portent les memes commandes — l'accueil, quand aucun fichier n'est
ouvert, et la fenetre d'un vaisseau. Elles les declarent une fois ici plutot que
deux fois avec deux ecarts.

Une fenetre qui installe ces menus expose trois signaux, et c'est tout ce que le
lanceur a besoin de connaitre d'elle :

    open_requested(str)   ouvrir ce fichier (un recent)
    browse_requested()    ouvrir la boite de dialogue
    about_requested()     afficher « a propos »
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtGui, QtWidgets

#: recents affiches dans le menu : la liste complete vit dans l'accueil
MENU_RECENTS = 8


def install_menus(window: QtWidgets.QMainWindow) -> QtWidgets.QMenu:
    """Ajoute Fichier et Aide a `window`. Renvoie le sous-menu des recents,
    que `fill_recent` remplit."""
    bar = window.menuBar()

    file_menu = bar.addMenu("&Fichier")
    open_action = file_menu.addAction("&Ouvrir un .nbt…")
    open_action.setShortcut(QtGui.QKeySequence("Ctrl+O"))
    open_action.triggered.connect(lambda: window.browse_requested.emit())

    recent_menu = file_menu.addMenu("Ouvrir un &récent")
    recent_menu.setEnabled(False)

    file_menu.addSeparator()
    quit_action = file_menu.addAction("&Quitter")
    quit_action.setShortcut(QtGui.QKeySequence("Ctrl+Q"))
    quit_action.triggered.connect(window.close)

    help_menu = bar.addMenu("&Aide")
    about_action = help_menu.addAction("À &propos de createsim")
    about_action.triggered.connect(lambda: window.about_requested.emit())
    return recent_menu


def fill_recent(window: QtWidgets.QMainWindow, menu: QtWidgets.QMenu,
                paths: list[Path]) -> None:
    """Remplit le sous-menu des recents. Vide, il se grise au lieu de disparaitre :
    un menu qui change de forme selon l'etat se retrouve mal."""
    menu.clear()
    shown = list(paths)[:MENU_RECENTS]
    menu.setEnabled(bool(shown))
    for path in shown:
        action = menu.addAction(path.name)
        action.setToolTip(str(path))
        action.setStatusTip(str(path))
        action.triggered.connect(
            lambda _checked=False, p=str(path): window.open_requested.emit(p))
