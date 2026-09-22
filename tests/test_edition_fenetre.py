"""L'edition dans la vraie fenetre (L5) : clic, gestes, encart, bandeau.

Le noyau d'edition est teste sans Qt dans `test_edition.py`. Ici, ce qui ne
se voit qu'avec la fenetre : qu'un clic selectionne, qu'une touche agisse,
que l'encart de diff dise la verite — et qu'apres une edition le bandeau ne
pilote pas des objets que la simulation ne lit plus.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="interface non installee")

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from createsim.sim.state import SimOptions  # noqa: E402

CARGO = "tests/fixtures/cargo_airship.nbt"


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        try:
            from createsim.view.cubes import default_format
            QtGui.QSurfaceFormat.setDefaultFormat(default_format())
            app = QtWidgets.QApplication([])
        except Exception as exc:                     # pragma: no cover
            pytest.skip("pas d'affichage disponible : %s" % exc)
    return app


@pytest.fixture
def window(qt_app):
    from pathlib import Path
    from createsim.view.app import VehicleWindow, _load
    path = str(Path(__file__).parent / "fixtures" / "cargo_airship.nbt")
    model, sim = _load(path, options=SimOptions())
    w = VehicleWindow(model, sim)
    w.resize(1200, 800)
    w.show()
    for _ in range(8):
        qt_app.processEvents()
    yield w
    w.close()


def _key(w, key):
    w.view.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key,
                                         QtCore.Qt.KeyboardModifier.NoModifier))


def test_un_clic_selectionne_un_bloc_et_ouvre_l_edition(window):
    window._block_clicked(window.view.width() / 2, window.view.height() / 2)
    assert window.selected in window.model.structure.blocks
    assert window.tabs.currentWidget() is window.editor
    assert window.editor.name.text() == window.model.structure.name(window.selected)


def test_un_clic_dans_le_vide_deselectionne(window):
    window._block_clicked(window.view.width() / 2, window.view.height() / 2)
    window._block_clicked(2, 2)
    assert window.selected is None
    assert "Aucun" in window.editor.name.text()


def test_suppr_supprime_et_l_encart_le_chiffre(window):
    window._block_clicked(window.view.width() / 2, window.view.height() / 2)
    pos = window.selected
    masse = window.model.organ("masse").total
    _key(window, QtCore.Qt.Key.Key_Delete)
    assert pos not in window.model.structure.blocks
    assert window.model.organ("masse").total < masse
    assert "1 édition" in window.diff_inset.title.text()


def test_annuler_revient_et_l_encart_le_dit(window):
    window._block_clicked(window.view.width() / 2, window.view.height() / 2)
    pos = window.selected
    _key(window, QtCore.Qt.Key.Key_Delete)
    window._gesture("annuler", None)
    assert pos in window.model.structure.blocks
    assert "aucune édition" in window.diff_inset.title.text()


def test_un_refus_s_affiche_sans_rien_casser(window):
    """F6.3 : deplacer sur une case occupee est refuse, et le dit."""
    blocks = window.model.structure.blocks
    a = next(p for p in sorted(blocks) if (p[0], p[1] + 1, p[2]) in blocks)
    window._select_block(a)
    _key(window, QtCore.Qt.Key.Key_PageUp)
    assert a in blocks
    assert "refus" in window.statusBar().currentMessage()
    assert not window.model.edited


def test_apres_une_breche_le_bandeau_pilote_les_bruleurs_vivants(window):
    """Le bandeau tient des references vers les bruleurs de l'organe. Apres
    un remplissage refait, la molette reglait un dictionnaire que la
    simulation ne lisait plus. Il doit pointer sur les bruleurs VIVANTS."""
    ballons = window.model.organ("ballons")
    mur = next(p for p in sorted(ballons.pockets[0].shell)
               if window.model.props.is_airtight(window.model.structure.name(p)))
    window._gesture("supprimer", mur)
    vivants = {id(b) for b in ballons.burners}
    for _key_, burners, _status in window.panel._burner_rows:
        for burner in burners:
            assert id(burner) in vivants, "reference perimee dans le bandeau"


def test_le_retour_a_l_original_vide_la_pile(window):
    window._block_clicked(window.view.width() / 2, window.view.height() / 2)
    for _ in range(3):
        if window.selected is None:
            break
        _key(window, QtCore.Qt.Key.Key_Delete)
        window._block_clicked(window.view.width() / 2, window.view.height() / 2)
    window._gesture("original", None)
    assert not window.model.edited
    assert not window.editor.undo.isEnabled()
