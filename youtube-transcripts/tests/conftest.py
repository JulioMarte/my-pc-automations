"""Opcion --network: habilita las pruebas que tocan YouTube de verdad."""


def pytest_addoption(parser):
    parser.addoption("--network", action="store_true", default=False,
                     help="ejecutar pruebas contra YouTube real")
