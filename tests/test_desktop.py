import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import brandops_desktop as bd
from app import server
from connectors import base
from tests.helpers import get, post

ROOT = Path(__file__).resolve().parent.parent


def test_app_home_per_platform(monkeypatch, tmp_path):
    monkeypatch.delenv("BRANDOPS_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(sys, "platform", "win32")
    assert bd.app_home() == tmp_path / "roaming" / "BrandOps"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert bd.app_home() == Path.home() / "Library" / "Application Support" / "BrandOps"
    monkeypatch.setenv("BRANDOPS_HOME", str(tmp_path / "custom"))
    assert bd.app_home() == tmp_path / "custom"


def test_prepare_home_seeds_defaults_without_overwriting(tmp_path):
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "brands.yaml").write_text("brands: []\n")
    home = bd.prepare_home(tmp_path / "home", defaults)
    assert (home / "config" / "brands.yaml").read_text() == "brands: []\n" and (home / "data_inbox").is_dir()
    (home / "config" / "brands.yaml").write_text("edited\n")
    bd.prepare_home(home, defaults)
    assert (home / "config" / "brands.yaml").read_text() == "edited\n"


def test_launcher_runs_headless_with_local_storage(tmp_path):
    port, home = bd.free_port(), tmp_path / "home"
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["BRANDOPS_HOME"] = str(home)
    proc = subprocess.Popen([sys.executable, "brandops_desktop.py", "--headless", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert bd.wait_ready(f"http://127.0.0.1:{port}", timeout=20)
        url = f"http://127.0.0.1:{port}"
        info = get(url + "/api/info")
        assert info["database"] == "sqlite" and info["desktop"] is True and info["demo"] is False
        assert info["inbox"] == str(home / "data_inbox")
        assert len(get(url + "/api/brands")["brands"]) == 7 and (home / "config" / "brands.yaml").exists()
        assert get(url + "/api/summary?days=30")["demo"] is False and (home / "brandops.db").exists()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_server_rejects_foreign_hosts_and_non_json_posts(app_url):
    req = urllib.request.Request(app_url + "/api/info", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    req = urllib.request.Request(app_url + "/api/brands", data=b'{"name":"X"}', headers={"Content-Type": "text/plain"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 415


def test_demo_toggle_only_in_desktop_mode(tmp_path, monkeypatch, app_url):
    monkeypatch.setattr(base, "BRANDS_PATH", base.BRANDS_PATH)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.delenv("BRANDOPS_DESKTOP", raising=False)
    assert post(app_url + "/api/demo", {"on": True})[0] == 400
    monkeypatch.setenv("BRANDOPS_DESKTOP", "1")
    try:
        assert post(app_url + "/api/demo", {"on": True})[1] == {"demo": True}
        assert len(get(app_url + "/api/summary?days=30")["brands"]) == 30
        assert post(app_url + "/api/demo", {"on": False})[1] == {"demo": False}
        assert len(get(app_url + "/api/summary?days=30")["brands"]) == 7
    finally:
        server.disable_demo()
