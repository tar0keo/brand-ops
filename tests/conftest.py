import threading

import pytest

from app import server, tasklog
from connectors import base


@pytest.fixture
def demo_mode(monkeypatch):
    monkeypatch.setattr(base, "BRANDS_PATH", base.BRANDS_PATH)  # restored after the test
    tasklog._MEM.clear()
    server.enable_demo()
    yield
    server.DEMO = False
    tasklog._MEM.clear()


@pytest.fixture
def app_url():
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
