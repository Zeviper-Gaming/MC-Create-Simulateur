"""Lancer l'outil et y charger un .nbt : executable, fenetre, glisser-deposer.

Charger un fichier depuis une fenetre, c'est aussi en charger un qui n'en est
pas un. Ces tests tiennent les deux : ce qui s'ouvre s'ouvre, et ce qui ne
s'ouvre pas le dit sans rien casser — la fenetre courante reste la, l'outil ne
se ferme pas, et l'utilisateur lit une phrase et non un `KeyError: 99`.

La premiere moitie n'a pas besoin de Qt : la configuration, le lecteur et le
choix de ce qui lance quoi tournent sans fenetre, comme le noyau.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import nbtlib
import pytest

from createsim import config, paths
from createsim.cli import wants_window
from createsim.data.nbt import Structure, StructureError
from createsim.data.tables import Tables

FIXTURES = Path(__file__).parent / "fixtures"
CARGO = FIXTURES / "cargo_airship.nbt"
CACHALOT = FIXTURES / "cachalot_volant_v3.nbt"


# --- un .nbt qui n'est pas une structure ------------------------------------
@pytest.fixture
def faux_nbt(tmp_path):
    """Trois fichiers que l'utilisateur peut prendre pour un vaisseau."""
    vide = tmp_path / "vide.nbt"
    vide.write_bytes(b"")
    texte = tmp_path / "texte.nbt"
    texte.write_bytes(b"ceci n'est pas du nbt")
    autre = tmp_path / "autre.nbt"                 # un vrai NBT, pas une structure
    nbtlib.File({"Data": nbtlib.Compound({"LevelName": nbtlib.String("monde")})}
                ).save(str(autre))
    return {"vide": vide, "texte": texte, "autre": autre}


def test_un_fichier_qui_n_est_pas_une_structure_le_dit(faux_nbt):
    for nom, path in faux_nbt.items():
        with pytest.raises(StructureError) as info:
            Structure(str(path))
        message = str(info.value)
        assert path.name in message, nom
        assert "KeyError" not in message.split("(")[0], \
            "%s : le message ne doit pas commencer par une trace" % nom


def test_un_nbt_qui_n_est_pas_une_structure_dit_ce_qui_manque(faux_nbt):
    with pytest.raises(StructureError) as info:
        Structure(str(faux_nbt["autre"]))
    message = str(info.value)
    assert "pas une structure" in message
    for champ in ("size", "palette", "blocks"):
        assert champ in message


def test_un_fichier_absent_reste_une_erreur_de_fichier(tmp_path):
    """Pas une `StructureError` : ce n'est pas le contenu qui est en cause."""
    with pytest.raises(FileNotFoundError):
        Structure(str(tmp_path / "absent.nbt"))


def test_un_vaisseau_valide_charge_toujours():
    assert len(Structure(str(CARGO)).blocks) == 5039


# --- la configuration -------------------------------------------------------
def test_le_dossier_utilisateur_se_redirige(monkeypatch, tmp_path):
    monkeypatch.setenv("CREATESIM_HOME", str(tmp_path / "ici"))
    assert config.user_dir() == tmp_path / "ici"
    assert config.log_path().parent == tmp_path / "ici"


def test_les_reglages_font_l_aller_retour(tmp_path):
    reglages = config.Settings(path=tmp_path / "reglages.json")
    reglages.add_recent(CARGO)
    assert reglages.save()
    relu = config.Settings.load(tmp_path / "reglages.json")
    assert relu.recent == reglages.recent
    assert relu.last_dir == str(CARGO.parent)


def test_le_fichier_de_reglages_se_lit_a_la_main(tmp_path):
    reglages = config.Settings(path=tmp_path / "reglages.json")
    reglages.add_recent(CARGO)
    reglages.save()
    texte = (tmp_path / "reglages.json").read_text(encoding="utf-8")
    assert json.loads(texte)["recent"], "format ouvert : du JSON, pas un registre"
    assert "\n" in texte


@pytest.mark.parametrize("contenu", ["", "pas du json", "[1, 2]", '{"recent": 3}',
                                     '{"recent": [1, null, "a"]}'])
def test_un_reglage_abime_ne_bloque_pas_le_lancement(tmp_path, contenu):
    """Perdre la liste des recents ne doit jamais empecher de lancer l'outil."""
    chemin = tmp_path / "reglages.json"
    chemin.write_text(contenu, encoding="utf-8")
    reglages = config.Settings.load(chemin)
    assert isinstance(reglages.recent, list)


def test_un_reglage_absent_donne_des_reglages_vides(tmp_path):
    assert config.Settings.load(tmp_path / "rien.json").recent == []


def test_les_recents_sont_sans_doublon_et_bornes(tmp_path):
    reglages = config.Settings(path=tmp_path / "r.json")
    for i in range(config.MAX_RECENT + 5):
        reglages.add_recent(tmp_path / ("v%d.nbt" % i))
    assert len(reglages.recent) == config.MAX_RECENT
    reglages.add_recent(tmp_path / ("v%d.nbt" % (config.MAX_RECENT + 4)))
    assert len(reglages.recent) == config.MAX_RECENT, "un doublon ne s'ajoute pas"
    assert reglages.recent[0].endswith("v%d.nbt" % (config.MAX_RECENT + 4))


def test_un_recent_deplace_disparait_de_la_liste(tmp_path):
    reglages = config.Settings(path=tmp_path / "r.json")
    copie = tmp_path / "copie.nbt"
    shutil.copy(CARGO, copie)
    reglages.add_recent(copie)
    assert reglages.recent_existing() == [copie.resolve()]
    copie.unlink()
    assert reglages.recent_existing() == [], "pas un piege dans la liste"


def test_une_ecriture_refusee_ne_plante_pas(tmp_path):
    """Un disque en lecture seule vaut mieux qu'une fermeture qui plante."""
    bloc = tmp_path / "fichier"
    bloc.write_text("x")
    reglages = config.Settings(path=bloc / "sous" / "r.json")   # parent = un fichier
    assert reglages.save() is False


# --- ou Create range ses fichiers -------------------------------------------
@pytest.fixture
def maison(monkeypatch, tmp_path):
    """Un faux dossier personnel avec deux instances CurseForge."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("CREATESIM_SCHEMATICS", raising=False)
    for nom in ("Alpha", "Beta"):
        dossier = tmp_path / "curseforge" / "minecraft" / "Instances" / nom / "schematics"
        dossier.mkdir(parents=True)
        shutil.copy(CARGO, dossier / "navire.nbt")
    (tmp_path / "curseforge" / "minecraft" / "Instances" / "Sans" / "mods").mkdir(parents=True)
    return tmp_path


def test_les_schematics_de_curseforge_sont_detectes(maison):
    trouves = config.schematics_dirs()
    assert [d.parent.name for d in trouves] == ["Alpha", "Beta"]
    assert all(d.name == "schematics" for d in trouves)


def test_une_instance_sans_schematics_est_ignoree(maison):
    assert "Sans" not in [d.parent.name for d in config.schematics_dirs()]


def test_la_variable_d_environnement_passe_en_premier(maison, monkeypatch):
    perso = maison / "ailleurs"
    perso.mkdir()
    monkeypatch.setenv("CREATESIM_SCHEMATICS", str(perso))
    assert config.schematics_dirs()[0] == perso


def test_un_dossier_de_schematics_ne_descend_pas_dans_uploaded(maison):
    dossier = config.schematics_dirs()[0]
    (dossier / "uploaded" / "joueur").mkdir(parents=True)
    shutil.copy(CARGO, dossier / "uploaded" / "joueur" / "copie.nbt")
    (dossier / "notes.txt").write_text("x")
    assert [p.name for p in config.nbt_files(dossier)] == ["navire.nbt"]


def test_le_dialogue_s_ouvre_la_ou_l_on_a_deja_ouvert(maison, tmp_path):
    reglages = config.Settings(path=tmp_path / "r.json")
    assert Path(reglages.start_dir()).parent.name == "Alpha", \
        "sans historique : le premier dossier de schematics"
    ailleurs = tmp_path / "dernier"
    ailleurs.mkdir()
    reglages.last_dir = str(ailleurs)
    assert reglages.start_dir() == str(ailleurs)
    ailleurs.rmdir()
    assert Path(reglages.start_dir()).parent.name == "Alpha", \
        "un dossier disparu ne doit pas etre propose"


# --- un executable n'a pas de console ---------------------------------------
def test_sans_console_les_prints_vont_au_journal(monkeypatch, tmp_path):
    """`sys.stdout` vaut None dans un executable sans console : le moindre
    `print` y leve une exception."""
    monkeypatch.setenv("CREATESIM_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    journal = config.prepare_streams()
    assert journal == tmp_path / config.LOG_NAME
    print("bonjour du journal")
    sys.stdout.flush()
    assert "bonjour du journal" in journal.read_text(encoding="utf-8")


def test_avec_une_console_rien_n_est_redirige(capsys):
    assert config.prepare_streams() is None


# --- les ressources : depot ou executable -----------------------------------
def test_depuis_les_sources_la_racine_est_celle_du_depot():
    assert (paths.data_dir() / "tables" / "manifest.json").is_file()
    assert paths.examples_dir() is not None
    assert (paths.examples_dir() / "cargo_airship.nbt").is_file()


@pytest.fixture
def paquet(monkeypatch, tmp_path):
    """Un faux dossier PyInstaller : les ressources a plat, exemples renommes."""
    racine = tmp_path / "_internal"
    shutil.copytree(paths.data_dir() / "tables", racine / "data" / "tables")
    shutil.copytree(paths.data_dir() / "scenarios", racine / "data" / "scenarios")
    (racine / "exemples").mkdir()
    shutil.copy(CARGO, racine / "exemples" / "cargo_airship.nbt")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(racine), raising=False)
    return racine


def test_dans_un_executable_les_ressources_sont_a_cote(paquet):
    assert paths.frozen()
    assert paths.bundle_root() == paquet
    assert paths.examples_dir() == paquet / "exemples"


def test_dans_un_executable_les_tables_viennent_du_paquet(paquet):
    tables = Tables.load()
    assert tables.directory == paquet / "data" / "tables"
    assert tables.get("pressure.gravity") > 0


def test_dans_un_executable_les_scenarios_retrouvent_leur_vaisseau(paquet):
    from createsim.sim.scenario import default_library, locate
    assert default_library() == paquet / "data" / "scenarios"
    assert locate("cargo_airship.nbt") == paquet / "exemples" / "cargo_airship.nbt"


# --- qui lance quoi ---------------------------------------------------------
@pytest.mark.parametrize("argv, fenetre", [
    ([], True),                                  # double-clic
    (["vaisseau.nbt"], True),                    # fichier glisse sur l'icone
    (["--capture", "x.png"], True),
    (["--bench", "3", "a.nbt"], True),
    (["--tables", "d", "a.nbt"], True),
    (["analyse", "a.nbt"], False),
    (["voir", "a.nbt"], False),
    (["run", "a.nbt", "--ticks", "5"], False),
    (["--tables", "d", "analyse", "a.nbt"], False),
    (["--tables=d", "validate"], False),
    (["--version"], False),
    (["-h"], False),
])
def test_qui_lance_quoi(argv, fenetre):
    assert wants_window(argv) is fenetre


def test_createsim_seul_ouvre_la_fenetre(monkeypatch):
    import createsim.gui
    recu = []
    monkeypatch.setattr(createsim.gui, "main", lambda argv: recu.append(argv) or 0)
    from createsim.cli import main
    assert main([]) == 0
    assert main(["vaisseau.nbt"]) == 0
    assert recu == [[], ["vaisseau.nbt"]]


def test_une_commande_reste_une_commande(monkeypatch, capsys):
    import createsim.gui
    monkeypatch.setattr(createsim.gui, "main",
                        lambda argv: pytest.fail("la fenetre ne doit pas s'ouvrir"))
    from createsim.cli import main
    assert main(["tables", "show", "--filtre", "universal_drag"]) == 0
    assert "universal_drag" in capsys.readouterr().out


def test_la_version_s_affiche_sans_qt(capsys):
    from createsim.gui import main
    with pytest.raises(SystemExit) as sortie:
        main(["--version"])
    assert sortie.value.code == 0
    assert "createsim" in capsys.readouterr().out


# ===========================================================================
# La fenetre
# ===========================================================================
@pytest.fixture
def lanceur(qt_app, tmp_path, monkeypatch):
    """Un lanceur isole : ses reglages vivent dans tmp_path, ses erreurs sont
    recueillies au lieu d'ouvrir une boite modale."""
    from createsim.view.launcher import Launcher
    monkeypatch.setenv("CREATESIM_HOME", str(tmp_path))
    launcher = Launcher(qt_app, Tables.load(),
                        config.Settings(path=tmp_path / "reglages.json"),
                        size=(900, 600))
    launcher.remember = True
    launcher.erreurs = []
    monkeypatch.setattr(launcher, "report_error",
                        lambda titre, message: launcher.erreurs.append((titre, message)))
    yield launcher
    for fenetre in (launcher.window, launcher.welcome):
        if fenetre is not None:
            fenetre.close()
    qt_app.removeEventFilter(launcher)
    launcher.deleteLater()


def _traiter(app, tours=6):
    from PySide6 import QtCore
    for _ in range(tours):
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
        QtCore.QCoreApplication.sendPostedEvents(None, 0)   # les deleteLater


def test_ouvrir_un_nbt_ouvre_la_fenetre_du_vaisseau(lanceur):
    assert lanceur.open(CARGO) is True
    assert lanceur.window is not None
    assert lanceur.window.name == "cargo_airship.nbt"
    assert "cargo_airship.nbt" in lanceur.window.windowTitle()
    assert lanceur.window.isVisible()
    assert lanceur.erreurs == []


def test_le_fichier_ouvert_est_retenu(lanceur, tmp_path):
    lanceur.open(CARGO)
    assert lanceur.settings.recent[0] == str(CARGO.resolve())
    relu = config.Settings.load(tmp_path / "reglages.json")
    assert relu.recent == lanceur.settings.recent, "ecrit sur disque, pas seulement en memoire"


def test_ouvrir_un_autre_remplace_la_fenetre(lanceur, qt_app):
    lanceur.open(CARGO)
    ancienne = lanceur.window
    ancienne.resize(1000, 640)
    assert lanceur.open(CACHALOT) is True
    _traiter(qt_app)

    assert lanceur.window is not ancienne
    assert lanceur.window.name == "cachalot_volant_v3.nbt"
    assert not ancienne.isVisible(), "un seul vaisseau a la fois"
    assert lanceur.window.size() == ancienne.size(), "meme taille"
    assert lanceur.window.isVisible(), "la fermeture de l'ancienne ne quitte pas l'outil"


def test_un_fichier_illisible_ne_change_rien(lanceur, faux_nbt):
    lanceur.open(CARGO)
    fenetre = lanceur.window

    assert lanceur.open(faux_nbt["autre"]) is False
    assert lanceur.window is fenetre, "la fenetre courante reste"
    assert fenetre.isVisible()
    titre, message = lanceur.erreurs[-1]
    assert "pas un vaisseau lisible" in titre
    assert "pas une structure" in message
    assert lanceur.settings.recent == [str(CARGO.resolve())], \
        "un fichier qui n'a pas charge n'entre pas dans les recents"


@pytest.mark.parametrize("nom", ["vide", "texte", "autre"])
def test_aucun_faux_fichier_ne_plante(lanceur, faux_nbt, nom):
    assert lanceur.open(faux_nbt[nom]) is False
    assert lanceur.window is None
    assert lanceur.erreurs and "KeyError" not in lanceur.erreurs[-1][1].split("(")[0]


def test_un_fichier_absent_est_signale(lanceur, tmp_path):
    assert lanceur.open(tmp_path / "absent.nbt") is False
    assert "introuvable" in lanceur.erreurs[-1][0].lower()


def test_sans_fichier_valide_l_accueil_s_ouvre(lanceur, faux_nbt):
    """Quitter juste apres l'erreur laisserait l'utilisateur devant rien."""
    lanceur.start([faux_nbt["texte"]])
    assert lanceur.window is None
    assert lanceur.welcome is not None and lanceur.welcome.isVisible()
    assert lanceur.erreurs


def test_sans_argument_l_accueil_s_ouvre(lanceur):
    lanceur.start([])
    assert lanceur.welcome.isVisible() and lanceur.window is None


def test_un_fichier_en_argument_ouvre_directement_le_vaisseau(lanceur):
    lanceur.start([CARGO])
    assert lanceur.window is not None and lanceur.welcome is None


def test_l_accueil_se_ferme_quand_un_vaisseau_s_ouvre(lanceur, qt_app):
    lanceur.show_welcome()
    accueil = lanceur.welcome
    lanceur.open(CARGO)
    _traiter(qt_app)
    assert not accueil.isVisible()
    assert lanceur.welcome is None


def test_plusieurs_fichiers_un_seul_est_ouvert(lanceur):
    """Le cahier tranche : un vaisseau a la fois."""
    assert lanceur.open_many([CARGO, CACHALOT]) is True
    assert lanceur.window.name == "cargo_airship.nbt"
    assert "1 autre" in lanceur.window.statusBar().currentMessage()


def test_la_boite_de_dialogue_ouvre_le_fichier_choisi(lanceur, monkeypatch):
    monkeypatch.setattr(lanceur, "pick_file", lambda: str(CACHALOT))
    lanceur.browse()
    assert lanceur.window.name == "cachalot_volant_v3.nbt"


def test_annuler_la_boite_de_dialogue_ne_fait_rien(lanceur, monkeypatch):
    lanceur.open(CARGO)
    monkeypatch.setattr(lanceur, "pick_file", lambda: None)
    fenetre = lanceur.window
    lanceur.browse()
    assert lanceur.window is fenetre and lanceur.erreurs == []


# --- les menus --------------------------------------------------------------
def test_le_menu_fichier_ouvre_la_boite_de_dialogue(lanceur, monkeypatch):
    from PySide6 import QtGui
    lanceur.open(CARGO)
    demandes = []
    monkeypatch.setattr(lanceur, "browse", lambda: demandes.append("dialogue"))
    lanceur.window.browse_requested.disconnect()
    lanceur.window.browse_requested.connect(lanceur.browse)

    actions = {a.text().replace("&", ""): a
               for a in lanceur.window.menuBar().actions()[0].menu().actions()}
    ouvrir = actions["Ouvrir un .nbt…"]
    assert ouvrir.shortcut() == QtGui.QKeySequence("Ctrl+O")
    ouvrir.trigger()
    assert demandes == ["dialogue"]


def test_le_menu_recents_suit_les_reglages(lanceur):
    lanceur.open(CARGO)
    lanceur.open(CACHALOT)
    menu = lanceur.window._recent_menu
    assert menu.isEnabled()
    noms = [a.text() for a in menu.actions()]
    assert noms == ["cachalot_volant_v3.nbt", "cargo_airship.nbt"], \
        "le plus recent d'abord"


def test_ouvrir_un_recent_depuis_le_menu(lanceur, qt_app):
    lanceur.open(CARGO)
    lanceur.open(CACHALOT)
    _traiter(qt_app)
    lanceur.window._recent_menu.actions()[1].trigger()     # cargo_airship
    _traiter(qt_app)
    assert lanceur.window.name == "cargo_airship.nbt"


def test_le_menu_recents_est_grise_quand_il_est_vide(lanceur):
    lanceur.settings.recent = []
    lanceur.open(CARGO)
    lanceur.settings.recent = []
    lanceur._refresh_recent()
    assert not lanceur.window._recent_menu.isEnabled()


# --- glisser-deposer --------------------------------------------------------
def _evenement(classe, fenetre, mime, position):
    from PySide6 import QtCore, QtWidgets
    evenement = classe(position, QtCore.Qt.DropAction.CopyAction, mime,
                       QtCore.Qt.MouseButton.LeftButton,
                       QtCore.Qt.KeyboardModifier.NoModifier)
    evenement.setAccepted(False)
    QtWidgets.QApplication.sendEvent(fenetre, evenement)
    return evenement


def _depot(fenetre, fichiers, type_evenement="drop"):
    """Simule un glisser-deposer d'explorateur sur `fenetre`.

    Un depot est toujours precede d'une entree : Qt n'achemine un `Drop` qu'au
    widget qui a accepte le `DragEnter` d'avant. Envoyer le depot seul, comme le
    faisait la premiere version de ce test, n'atteint personne.
    """
    from PySide6 import QtCore, QtGui
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(f)) for f in fichiers])
    entree = _evenement(QtGui.QDragEnterEvent, fenetre, mime, QtCore.QPoint(20, 20))
    if type_evenement == "enter":
        return entree, mime
    depot = _evenement(QtGui.QDropEvent, fenetre, mime, QtCore.QPointF(20, 20))
    return depot, mime


def test_un_nbt_glisse_sur_l_accueil_est_accepte_puis_ouvert(lanceur, qt_app):
    lanceur.show_welcome()
    entree, _m = _depot(lanceur.welcome, [CARGO], "enter")
    assert entree.isAccepted(), "la fenetre doit annoncer qu'elle prend le fichier"

    _depot(lanceur.welcome, [CARGO], "drop")
    assert lanceur.window is None, "ouvrir dans le gestionnaire bloquerait l'explorateur"
    _traiter(qt_app)
    assert lanceur.window is not None
    assert lanceur.window.name == "cargo_airship.nbt"


def test_un_nbt_glisse_sur_un_vaisseau_le_remplace(lanceur, qt_app):
    lanceur.open(CARGO)
    _depot(lanceur.window, [CACHALOT])
    _traiter(qt_app)
    assert lanceur.window.name == "cachalot_volant_v3.nbt"


def test_un_nbt_glisse_sur_un_champ_de_saisie_marche_aussi(lanceur, qt_app):
    """Un champ de saisie accepte les depots par defaut et refuserait un fichier
    qu'il ne comprend pas : c'est pourquoi le lanceur filtre au niveau de
    l'application et non de chaque fenetre."""
    from PySide6 import QtWidgets
    lanceur.open(CARGO)
    champ = lanceur.window.findChildren(QtWidgets.QLineEdit)[0]
    _depot(champ, [CACHALOT])
    _traiter(qt_app)
    assert lanceur.window.name == "cachalot_volant_v3.nbt"


def test_un_fichier_qui_n_est_pas_un_nbt_est_refuse(lanceur, tmp_path):
    autre = tmp_path / "notes.txt"
    autre.write_text("x")
    entree, _m = _depot(lanceur.welcome or _accueil(lanceur), [autre], "enter")
    assert not entree.isAccepted()


def _accueil(lanceur):
    lanceur.show_welcome()
    return lanceur.welcome


def test_plusieurs_nbt_glisses_n_en_ouvrent_qu_un(lanceur, qt_app):
    lanceur.show_welcome()
    _depot(lanceur.welcome, [CARGO, CACHALOT])
    _traiter(qt_app)
    assert lanceur.window.name == "cargo_airship.nbt"
    assert "un seul vaisseau" in lanceur.window.statusBar().currentMessage()


def test_un_nbt_glisse_qui_n_est_pas_un_vaisseau_le_dit(lanceur, qt_app, faux_nbt):
    lanceur.open(CARGO)
    fenetre = lanceur.window
    _depot(fenetre, [faux_nbt["autre"]])
    _traiter(qt_app)
    assert lanceur.window is fenetre
    assert lanceur.erreurs


# --- l'accueil --------------------------------------------------------------
def test_l_accueil_liste_les_exemples(lanceur):
    lanceur.show_welcome()
    noms = [Path(p).name for p in lanceur.welcome.file_items()]
    assert "cargo_airship.nbt" in noms and "cachalot_volant_v3.nbt" in noms


def test_l_accueil_place_les_recents_en_premier(lanceur):
    lanceur.open(CACHALOT)
    lanceur.window.close()
    lanceur.window = None
    lanceur.show_welcome()
    assert Path(lanceur.welcome.file_items()[0]).name == "cachalot_volant_v3.nbt"


def test_activer_un_fichier_de_l_accueil_l_ouvre(lanceur, qt_app):
    lanceur.show_welcome()
    liste = lanceur.welcome.list
    cible = next(liste.item(i) for i in range(liste.count())
                 if (liste.item(i).data(0x100) or "").endswith("cargo_airship.nbt"))
    liste.itemActivated.emit(cible)
    _traiter(qt_app)
    assert lanceur.window.name == "cargo_airship.nbt"


def test_un_en_tete_de_section_n_est_pas_activable(lanceur):
    lanceur.show_welcome()
    ouvertures = []
    lanceur.welcome.open_requested.connect(ouvertures.append)
    liste = lanceur.welcome.list
    entete = liste.item(0)
    assert entete.data(0x100) is None
    liste.itemActivated.emit(entete)
    assert ouvertures == []


def test_un_accueil_sans_rien_a_proposer_le_dit(qt_app):
    from createsim.view.welcome import WelcomeWindow
    accueil = WelcomeWindow([])
    assert accueil.list.count() == 1
    assert "Aucun vaisseau" in accueil.list.item(0).text()
    assert accueil.file_items() == []


def test_un_recent_disparu_n_est_pas_propose(lanceur, tmp_path):
    lanceur.settings.recent = [str(tmp_path / "disparu.nbt")]
    titres = [s.title for s in lanceur.sections()]
    section = lanceur.sections()[0]
    assert section.files == [], "%s : rien a lister" % titres[0]


# --- modes de diagnostic ----------------------------------------------------
def test_la_capture_enregistre_la_fenetre(lanceur, tmp_path):
    lanceur.start([CARGO])
    png = tmp_path / "sortie" / "vaisseau.png"
    assert lanceur.capture(str(png), settle=0.2) == 0
    assert png.is_file() and png.stat().st_size > 5000, \
        "une vue 3D vide fait quelques centaines d'octets"


def test_un_lancement_scripte_ne_pollue_pas_les_recents(qt_app, tmp_path):
    from createsim.view.launcher import Launcher
    reglages = config.Settings(path=tmp_path / "r.json")
    scripte = Launcher(qt_app, Tables.load(), reglages, interactive=False)
    try:
        scripte.open(CARGO)
        assert reglages.recent == []
        assert not (tmp_path / "r.json").exists()
    finally:
        scripte.window.close()
        qt_app.removeEventFilter(scripte)


def test_le_point_d_entree_mesure_la_cadence_et_sort(qt_app, tmp_path, monkeypatch):
    """Ce que fait `createsim.exe vaisseau.nbt --bench 1`, de bout en bout."""
    import createsim.gui
    monkeypatch.setenv("CREATESIM_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)   # `run` en installe un
    assert createsim.gui.main([str(CARGO), "--bench", "0.5",
                               "--largeur", "800", "--hauteur", "500"]) == 0
    assert not (tmp_path / "reglages.json").exists()


def test_le_point_d_entree_sort_en_erreur_sans_vaisseau_a_mesurer(qt_app, tmp_path, monkeypatch):
    import createsim.gui
    monkeypatch.setenv("CREATESIM_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    assert createsim.gui.main([str(tmp_path / "absent.nbt"), "--bench", "0.2"]) == 2


# --- l'a-propos -------------------------------------------------------------
def test_l_a_propos_dit_d_ou_viennent_les_constantes(lanceur, monkeypatch):
    from PySide6 import QtWidgets
    vu = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "about",
                        staticmethod(lambda parent, titre, texte: vu.append(texte)))
    lanceur.about()
    texte = vu[0]
    assert "createsim 0.1.0" in texte
    assert "create 6.0.10" in texte, "la version de mod dont viennent les tables"
    assert "Journal" in texte
