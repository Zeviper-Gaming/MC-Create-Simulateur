"""L'executable : ce qu'on peut verifier sans le construire.

Construire l'executable prend plusieurs minutes et exige PyInstaller ; ces tests
n'en ont besoin ni l'un ni l'autre. Ils tiennent ce qui casse un paquet avant
meme qu'on le construise — un fichier de donnees que la description nomme mais
qui n'existe plus, une icone corrompue, un script de construction qui plante au
lieu de dire ce qui manque.

La verification de l'executable construit, elle, est faite par
`packaging/build_exe.py` : elle lance le paquet et non les sources.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
sys.path.insert(0, str(PACKAGING))


# --- la description PyInstaller ---------------------------------------------
def _executer_spec(monkeypatch, un_fichier: bool):
    """Execute createsim.spec avec des doublures de PyInstaller et rend ce qu'il
    a demande : on lit la description sans rien construire."""
    monkeypatch.setenv("CREATESIM_ONEFILE", "1" if un_fichier else "0")
    appels: list[tuple[str, tuple, dict]] = []

    class Analyse:
        def __init__(self, scripts, **kw):
            self.scripts, self.kw = scripts, kw
            self.pure, self.binaries, self.datas = [], [], []

    def doublure(nom):
        def appeler(*args, **kw):
            appels.append((nom, args, kw))
            return object()
        return appeler

    def analyse(scripts, **kw):
        appels.append(("Analysis", (scripts,), kw))
        return Analyse(scripts, **kw)

    espace = {"SPECPATH": str(PACKAGING), "Analysis": analyse,
              "PYZ": doublure("PYZ"), "EXE": doublure("EXE"),
              "COLLECT": doublure("COLLECT")}
    source = (PACKAGING / "createsim.spec").read_text(encoding="utf-8")
    exec(compile(source, str(PACKAGING / "createsim.spec"), "exec"), espace)
    return appels


def test_la_description_se_lit(monkeypatch):
    appels = _executer_spec(monkeypatch, un_fichier=False)
    assert [nom for nom, _a, _k in appels] == ["Analysis", "PYZ", "EXE", "COLLECT"]


def test_un_seul_fichier_n_a_pas_de_dossier(monkeypatch):
    appels = _executer_spec(monkeypatch, un_fichier=True)
    assert [nom for nom, _a, _k in appels] == ["Analysis", "PYZ", "EXE"]


def test_chaque_fichier_de_donnees_nomme_existe(monkeypatch):
    """Un fichier de donnees renomme ne fait pas echouer la construction : le
    paquet demarre, et plante a la premiere lecture de ce fichier."""
    appels = _executer_spec(monkeypatch, un_fichier=False)
    analyse = next(kw for nom, _a, kw in appels if nom == "Analysis")
    assert analyse["datas"]
    for source, _destination in analyse["datas"]:
        assert Path(source).exists(), source


def test_l_executable_embarque_ce_qu_il_lit_a_l_execution(monkeypatch):
    appels = _executer_spec(monkeypatch, un_fichier=False)
    analyse = next(kw for nom, _a, kw in appels if nom == "Analysis")
    destinations = {d for _s, d in analyse["datas"]}
    assert {"data/tables", "data/scenarios", "assets", "exemples"} <= destinations

    exemples = {Path(s).name for s, d in analyse["datas"] if d == "exemples"}
    assert {"cargo_airship.nbt", "cachalot_volant_v3.nbt"} <= exemples


def test_le_chemin_des_sources_est_donne(monkeypatch):
    appels = _executer_spec(monkeypatch, un_fichier=False)
    analyse = next(kw for nom, _a, kw in appels if nom == "Analysis")
    assert str(ROOT / "src") in analyse["pathex"]


def test_l_executable_n_a_pas_de_console(monkeypatch):
    """Une fenetre de console derriere l'application, a chaque double-clic."""
    appels = _executer_spec(monkeypatch, un_fichier=False)
    exe = next(kw for nom, _a, kw in appels if nom == "EXE")
    assert exe["console"] is False


def test_l_entree_appelle_le_point_d_entree_graphique():
    source = (PACKAGING / "entry.py").read_text(encoding="utf-8")
    assert "from createsim.gui import main" in source
    compile(source, "entry.py", "exec")


# --- l'icone ----------------------------------------------------------------
def test_les_deux_icones_existent():
    assert (ROOT / "assets" / "createsim.png").is_file()
    assert (ROOT / "assets" / "createsim.ico").is_file()


def test_l_ico_est_un_ico_valide_a_plusieurs_tailles():
    """Windows choisit la taille selon le contexte (barre des taches, liste,
    explorateur) : un ico a une seule taille donne une icone floue ailleurs."""
    donnees = (ROOT / "assets" / "createsim.ico").read_bytes()
    reserve, genre, nombre = struct.unpack_from("<HHH", donnees, 0)
    assert (reserve, genre) == (0, 1)
    assert nombre >= 6

    tailles = []
    for i in range(nombre):
        largeur, hauteur, _c, _r, _p, _b, taille, decalage = struct.unpack_from(
            "<BBBBHHII", donnees, 6 + 16 * i)
        tailles.append(largeur or 256)
        assert donnees[decalage:decalage + 8] == b"\x89PNG\r\n\x1a\n", \
            "chaque image de l'ico est un PNG"
        assert decalage + taille <= len(donnees)
    assert 256 in tailles and 16 in tailles and 32 in tailles


def test_le_png_de_la_fenetre_est_une_vraie_image(qt_app):
    from PySide6 import QtGui
    image = QtGui.QImage(str(ROOT / "assets" / "createsim.png"))
    assert not image.isNull()
    assert (image.width(), image.height()) == (256, 256)
    assert image.hasAlphaChannel(), "les coins arrondis sont transparents"
    assert image.pixelColor(0, 0).alpha() == 0


def test_l_icone_est_reproductible():
    """Generee par le code : la regenerer donne les memes octets, donc un ecart
    dans le depot est une retouche voulue et non un fichier dont on ignore
    l'origine."""
    pytest.importorskip("PySide6")
    import make_icon
    from PySide6 import QtGui
    QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    image = make_icon.draw(256)
    enregistree = QtGui.QImage(str(ROOT / "assets" / "createsim.png")
                               ).convertToFormat(image.format())
    assert image == enregistree


def test_le_lanceur_utilise_l_icone_embarquee():
    from createsim import paths
    assert paths.asset("createsim.png") is not None


# --- le script de construction ----------------------------------------------
def test_sans_pyinstaller_le_script_le_dit(monkeypatch, capsys):
    """Une trace d'import ne dit pas quoi installer."""
    import build_exe
    monkeypatch.setitem(sys.modules, "PyInstaller", None)   # force l'ImportError
    assert build_exe.build(onefile=False, clean=False) == 3
    assert "pip install" in capsys.readouterr().err


def test_le_nom_de_l_executable_depend_de_la_forme(monkeypatch):
    import build_exe
    dossier = build_exe.executable(onefile=False)
    seul = build_exe.executable(onefile=True)
    assert dossier.parent.name == "createsim"
    assert seul.parent.name == "dist"
    assert dossier.name == seul.name == build_exe.EXE_NAME


def test_le_paquet_declare_son_point_d_entree_et_son_extra():
    import tomllib
    projet = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert projet["project"]["gui-scripts"]["createsim-gui"] == "createsim.gui:main"
    assert any("pyinstaller" in d.lower()
               for d in projet["project"]["optional-dependencies"]["build"])


def test_la_version_du_paquet_et_celle_du_code_concordent():
    import tomllib

    import createsim
    projet = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert projet["project"]["version"] == createsim.__version__
