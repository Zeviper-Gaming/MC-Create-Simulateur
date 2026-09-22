"""Ce que L6 ajoute a la fenetre : l'assiette au rendu et la coupe (F3.4, F3.3).

La physique de rotation est testee sans Qt dans `test_assiette.py`. Ici, ce qui
ne se voit qu'avec la fenetre : que la coque tourne autour de son centre de
masse et pas autour de l'origine, que la coupe ouvre le bon cote, que les
fleches de force ne soient jamais coupees — et que la coupe ne se referme pas
toute seule apres une edition.
"""
from __future__ import annotations

import math

import pytest

pytest.importorskip("PySide6", reason="interface non installee")

from PySide6 import QtGui  # noqa: E402

from createsim.sim import rotation as R  # noqa: E402
from createsim.sim.state import SimOptions  # noqa: E402

CARGO = "tests/fixtures/cargo_airship.nbt"

#: le plan « rien de coupe » : une distance inatteignable
OUVERT = 1.0e9


@pytest.fixture
def window(qt_app):
    from pathlib import Path
    from createsim.view.app import VehicleWindow, _load
    path = str(Path(__file__).parent / "fixtures" / "cargo_airship.nbt")
    model, sim = _load(path, options=SimOptions())
    w = VehicleWindow(model, sim)
    w.resize(1100, 760)
    w.show()
    for _ in range(8):
        qt_app.processEvents()
    yield w
    w.close()


# --- la coupe ---------------------------------------------------------------
def test_la_coupe_pose_le_bon_plan(window):
    """`dot(position, normale) > distance` jette le fragment. Coupe sur y a 12 :
    tout ce qui est au-dessus de 12 disparait. Retournee : tout ce qui est
    dessous."""
    window.view.set_cut(None)
    assert window.view.cut.w() >= OUVERT

    window.view.set_cut(1, 12.0)
    assert (window.view.cut.x(), window.view.cut.y(), window.view.cut.z(),
            window.view.cut.w()) == (0.0, 1.0, 0.0, 12.0)

    window.view.set_cut(1, 12.0, reverse=True)
    assert (window.view.cut.x(), window.view.cut.y(), window.view.cut.z(),
            window.view.cut.w()) == (0.0, -1.0, 0.0, -12.0)


def test_la_barre_de_coupe_ouvre_a_mi_coque(window):
    """Choisir un axe doit montrer quelque chose. Une coupe qui demarre a zero
    n'affiche rien du tout et se lit comme un vaisseau disparu."""
    bar = window.cut_bar
    assert bar.state()[0] is None
    assert not bar.slider.isEnabled()

    bar.axis.setCurrentIndex(bar.axis.findData(2))   # l'axe z, le long
    axis, offset, reverse = bar.state()
    assert axis == 2
    assert bar.slider.isEnabled()
    assert offset == pytest.approx(window.model.structure.size[2] // 2)
    assert not reverse
    assert window.view.cut.z() == 1.0

    bar.reverse.setChecked(True)
    assert window.view.cut.z() == -1.0

    bar.axis.setCurrentIndex(bar.axis.findData(None))   # « aucune »
    assert bar.state()[0] is None
    assert window.view.cut.w() >= OUVERT


def test_la_coupe_ne_prend_pas_le_clavier(window):
    """Les fleches deplacent le bloc selectionne (F6.2). Un curseur qui capte le
    focus au premier clic volerait le geste d'edition sans prevenir."""
    from PySide6 import QtCore
    for widget in (window.cut_bar.axis, window.cut_bar.slider,
                   window.cut_bar.reverse):
        assert widget.focusPolicy() == QtCore.Qt.FocusPolicy.NoFocus


def test_la_coupe_survit_a_une_edition(window):
    """Le bandeau de commandes est reconstruit a chaque edition qui touche un
    levier ; la coupe vit dans la FENETRE, pas dedans. Elle doit rester ouverte
    au meme endroit apres une suppression de bloc."""
    window.cut_bar.axis.setCurrentIndex(window.cut_bar.axis.findData(2))
    avant = (window.view.cut.x(), window.view.cut.y(), window.view.cut.z(),
             window.view.cut.w())

    pos = next(iter(window.model.structure.blocks))
    window.selected = pos
    window._edit_key("supprimer")

    assert (window.view.cut.x(), window.view.cut.y(), window.view.cut.z(),
            window.view.cut.w()) == avant
    assert window.cut_bar.state()[0] == 2


# --- l'assiette au rendu ----------------------------------------------------
def test_l_assiette_tourne_autour_du_centre_de_masse(window):
    """C'est le centre de masse qui suit la trajectoire, le reste tourne autour.
    Tourner autour de l'origine de la structure ferait deriver le vaisseau hors
    du cadre des le premier degre."""
    com = window.sim.mass.com
    quart = (math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4))
    window.view.set_attitude(quart, com)

    fixe = window.view.model.map(QtGui.QVector3D(*[float(v) for v in com]))
    assert fixe.x() == pytest.approx(com[0], abs=1e-3)
    assert fixe.y() == pytest.approx(com[1], abs=1e-3)
    assert fixe.z() == pytest.approx(com[2], abs=1e-3)

    # un point a un metre devant, amene sur le cote par le quart de tour
    devant = QtGui.QVector3D(float(com[0]) + 1.0, float(com[1]), float(com[2]))
    tourne = window.view.model.map(devant)
    assert tourne.x() == pytest.approx(com[0], abs=1e-3)
    assert tourne.y() == pytest.approx(com[1] + 1.0, abs=1e-3)


def test_la_fenetre_applique_l_assiette_simulee(window, qt_app):
    """Apres quelques centaines de ticks le cargo pique du nez. La matrice de
    rendu doit avoir bouge avec lui — sinon l'assiette n'existe que dans le
    rapport."""
    window.sim.run(400)
    window._refresh_scene()
    qt_app.processEvents()

    assert window.sim.state.orientation != R.IDENTITY
    assert not window.view.model.isIdentity()


def test_le_bandeau_affiche_tangage_et_roulis(window):
    """Le bras de levier dit le desequilibre statique ; le tangage dit ou le
    vaisseau en est. Les deux doivent etre lisibles cote a cote."""
    window.sim.run(400)
    window.hud.set_report(window.name, window.sim.report(), window.overlay_data)

    noms = [nom for nom, _valeur, _gros in window.hud.instruments]
    assert "tangage" in noms and "roulis" in noms

    valeurs = dict((nom, valeur) for nom, valeur, _ in window.hud.instruments)
    assert "deg" in valeurs["tangage"]


def test_rotation_coupee_laisse_le_rendu_a_plat(qt_app):
    """`rotation=False` : le bandeau n'affiche plus d'assiette et la matrice de
    rendu reste l'identite. Le lot L6 doit pouvoir se debrancher entierement."""
    from pathlib import Path
    from createsim.view.app import VehicleWindow, _load

    path = str(Path(__file__).parent / "fixtures" / "cargo_airship.nbt")
    model, sim = _load(path, options=SimOptions(rotation=False))
    w = VehicleWindow(model, sim)
    try:
        w.sim.run(400)
        w._refresh_scene()
        w.hud.set_report(w.name, w.sim.report(), w.overlay_data)

        assert w.view.model.isIdentity()
        noms = [nom for nom, _valeur, _gros in w.hud.instruments]
        assert "tangage" not in noms
    finally:
        w.close()
