def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: tests that take >5s (load + train a model)"
    )
