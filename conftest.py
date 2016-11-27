def pytest_addoption(parser):
    parser.addoption("--ip_address", action="store", default=None, help="IP Address of MazeRunner")
    parser.addoption("--json_credentials", action="store", default=None, help="Json file with the relevant credentials")
