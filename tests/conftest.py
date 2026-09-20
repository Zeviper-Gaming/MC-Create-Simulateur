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


@pytest.fixture(scope="session")
def tables() -> Tables:
    return Tables.load()


@pytest.fixture
def cargo(tables) -> VehicleModel:
    return VehicleModel.load(str(CARGO), tables)


@pytest.fixture
def sim(cargo) -> Simulation:
    return Simulation(cargo, SimOptions())
