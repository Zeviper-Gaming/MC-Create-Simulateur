"""Telemetrie, courbes et diagnostic (L3).

Le cahier demande l'enregistrement des FORCES PAR SOURCE, pas seulement par
famille : c'est ce qui permet de rejouer une trace et de savoir laquelle des
six helices a molli.
"""
from __future__ import annotations

import pytest

from createsim.sim.state import SimOptions
from createsim.sim.telemetry import BASE_COLUMNS, MAX_ROWS, Trace
from createsim.sim.tick import Simulation


@pytest.fixture
def trace(cargo):
    sim = Simulation(cargo, SimOptions(initial_gas="vide"))
    recording = Trace()
    recording.record(sim)
    for _ in range(200):
        sim.step()
        recording.record(sim)
    return recording, sim


# --- enregistrement ---------------------------------------------------------
def test_un_enregistrement_par_tick(trace):
    recording, _sim = trace
    assert len(recording) == 201
    assert recording.rows[0]["tick"] == 0
    assert recording.rows[-1]["tick"] == 200
    assert recording.rows[-1]["temps_s"] == pytest.approx(10.0)


def test_les_forces_sont_enregistrees_par_source(trace):
    """« forces par source » : agreger par famille ne suffit pas."""
    recording, _sim = trace
    assert "gravite" in recording.force_keys
    assert any(k.startswith("helice@") for k in recording.force_keys), \
        recording.force_keys
    for key in recording.force_keys:
        for axis in "xyz":
            assert "f_%s_%s" % (key, axis) in recording.columns


def test_l_identite_des_forces_ne_change_pas_en_cours_de_route(trace):
    """Une helice a l'arret reste dans la liste, a zero."""
    recording, _sim = trace
    first = set(k for k in recording.rows[0] if k.startswith("f_"))
    last = set(k for k in recording.rows[-1] if k.startswith("f_"))
    assert first == last


def test_les_colonnes_de_base_sont_toutes_la(trace):
    recording, _sim = trace
    for column in BASE_COLUMNS:
        assert column in recording.rows[0], column


def test_l_echantillonnage_allege_la_trace(cargo):
    sim = Simulation(cargo)
    recording = Trace(every=10)
    recording.record(sim)
    for _ in range(100):
        sim.step()
        recording.record(sim)
    assert 5 <= len(recording) <= 15


def test_la_trace_ne_grossit_pas_sans_fin(cargo, monkeypatch):
    import createsim.sim.telemetry as telemetry
    monkeypatch.setattr(telemetry, "MAX_ROWS", 20)
    sim = Simulation(cargo)
    recording = telemetry.Trace()
    for _ in range(60):
        sim.step()
        recording.record(sim)
    assert len(recording) == 20
    assert recording.truncated is True


# --- fichier ----------------------------------------------------------------
def test_aller_retour_csv_exact(trace, tmp_path):
    recording, _sim = trace
    path = recording.to_csv(str(tmp_path / "trace.csv"))
    relu = Trace.from_csv(path)

    assert len(relu) == len(recording)
    assert relu.force_keys == recording.force_keys
    for column in recording.columns:
        avant = recording.rows[100].get(column, 0.0) or 0.0
        apres = relu.rows[100].get(column, 0.0) or 0.0
        assert float(avant) == pytest.approx(float(apres), abs=1e-6), column


def test_le_csv_est_lisible_a_la_main(trace, tmp_path):
    """Format ouvert : un en-tete, une ligne par tick, rien de binaire."""
    recording, _sim = trace
    path = recording.to_csv(str(tmp_path / "trace.csv"))
    lignes = open(path, encoding="utf-8").read().splitlines()
    assert lignes[0].startswith("tick,temps_s,")
    assert "f_gravite_y" in lignes[0]
    assert len(lignes) == len(recording) + 1


def test_les_vecteurs_se_relisent_par_clef(trace, tmp_path):
    recording, sim = trace
    relu = Trace.from_csv(recording.to_csv(str(tmp_path / "t.csv")))
    vecteurs = relu.vectors_at(100)
    assert set(vecteurs) == set(recording.force_keys)
    poids = vecteurs["gravite"]
    assert poids[1] < 0, "le poids tire vers le bas"
    assert poids[1] == pytest.approx(-sim.mass.total
                                     * cargo_gravity(sim), rel=1e-4)


def cargo_gravity(sim):
    return sim.tables.get("pressure.gravity")


def test_une_fenetre_glissante_ne_renvoie_que_la_fin(trace):
    recording, _sim = trace
    fenetre = recording.window(3.0)
    assert fenetre
    assert fenetre[-1] is recording.rows[-1]
    duree = fenetre[-1]["temps_s"] - fenetre[0]["temps_s"]
    assert duree <= 3.0 + 1e-6


# --- ce que la courbe doit montrer ------------------------------------------
def test_la_trace_montre_la_montee_et_sa_convergence(cargo):
    """« C'est la qu'on voit un vaisseau osciller autour de son altitude
    d'equilibre au lieu de s'y poser. »"""
    sim = Simulation(cargo, SimOptions(initial_gas="vide"))
    recording = Trace()
    recording.record(sim)
    for _ in range(4000):
        sim.step()
        recording.record(sim)

    altitudes = recording.column("y")
    gaz = recording.column("gaz_total")
    assert gaz[0] == 0.0 and gaz[-1] > gaz[0], "le ballon se remplit"
    assert min(altitudes) < altitudes[0], "il commence par descendre, a vide"
    assert altitudes[-1] > altitudes[0], "puis il monte"
    fin = altitudes[-50:]
    assert max(fin) - min(fin) < 0.05, "et il se stabilise"


def test_les_series_de_courbes_existent_dans_la_trace(trace):
    pytest.importorskip("PySide6")
    from createsim.view.curves import SERIES
    recording, _sim = trace
    for name, (column, _color, _unit) in SERIES.items():
        assert column in recording.rows[0], "%s -> %s" % (name, column)
