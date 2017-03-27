def pytest_addoption(parser):
    parser.addoption("--json_credentials", action="store", default=None,
                     help="Json file with the relevant credentials")
    parser.addoption("--runslow", action="store_true", default=False, help="Run slow tests")
    parser.addoption("--lab_dependent", action="store_true", default=False,
                     help="Run tests that depend on the lab resources")
