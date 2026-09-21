"""Fixtures partagees.

Le noyau tourne sans fenetre : tout ce qui suit s'execute en ligne de commande,
sans jeu et sans intervention.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from createsim.data.tables import Tables
from createsim.model.vehicle import VehicleModel
from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation

FIXTURES = Path(__file__).parent / "fixtures"
CARGO = FIXTURES / "cargo_airship.nbt"

#: vaisseaux hors depot : leurs tests sont ignores quand ils sont absents,
#: jamais comptes en echec
INSTANCE = Path(r"C:/Users/Florian/curseforge/minecraft/Instances"
                r"/La Bonne Compagnie/schematics")


@pytest.fixture(scope="session")
def tables() -> Tables:
    return Tables.load()


@pytest.fixture
def cargo(tables) -> VehicleModel:
    return VehicleModel.load(str(CARGO), tables)


@pytest.fixture
def sim(cargo) -> Simulation:
    return Simulation(cargo, SimOptions())


@pytest.fixture
def cachalot_model(tables) -> VehicleModel:
    """Contraptions assemblees, jauges, transmission decouplee a 15."""
    return VehicleModel.load(str(FIXTURES / "cachalot_volant_v3.nbt"), tables)


def _hors_depot(name: str, tables) -> VehicleModel:
    path = INSTANCE / name
    if not path.is_file():
        pytest.skip("vaisseau hors depot : %s" % name)
    return VehicleModel.load(str(path), tables)


@pytest.fixture
def cruiser_model(tables) -> VehicleModel:
    """20 659 blocs, 839 etanches, 1 592 levitite, 16 voiles de coque."""
    return _hors_depot("c1_air_cruiser.nbt", tables)


@pytest.fixture
def cachalot_v4_model(tables) -> VehicleModel:
    """174 voiles, toutes sur des rotors de palier."""
    return _hors_depot("cachalot_volant_v4.nbt", tables)


@pytest.fixture(scope="session")
def qt_app():
    """Une seule QApplication pour toute la session : Qt n'en admet qu'une."""
    pytest.importorskip("PySide6", reason="interface non installee")
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        try:
            app = QtWidgets.QApplication([])
        except Exception as exc:                     # pragma: no cover
            pytest.skip("pas d'affichage disponible : %s" % exc)
    return app
