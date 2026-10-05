"""Desktop launcher: runs the app in a native window with all data kept in one local folder."""
import argparse
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def app_home():
    if os.environ.get("BRANDOPS_HOME"):
        return Path(os.environ["BRANDOPS_HOME"])
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "BrandOps"


def defaults_dir():
    return Path(getattr(sys, "_MEIPASS", ROOT)) / "config"


def prepare_home(home, defaults=None):
    """Create the data folder and copy in default settings. Existing files are never overwritten."""
    defaults = Path(defaults) if defaults else defaults_dir()
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "data_inbox").mkdir(exist_ok=True)
    for f in defaults.glob("*.yaml"):
        target = home / "config" / f.name
        if not target.exists():
            shutil.copy(f, target)
    return home


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/api/info", timeout=1).read()
            return True
        except Exception:
            time.sleep(0.2)
    return False


def _webview():
    try:
        import webview
        return webview
    except Exception:
        return None


def main(argv=None):
    p = argparse.ArgumentParser(description="Brand operations desktop app")
    p.add_argument("--demo", action="store_true", help="start with built-in sample brands and fake data")
    p.add_argument("--browser", action="store_true", help="open in your web browser instead of a native window")
    p.add_argument("--headless", action="store_true", help="run the server only (for testing)")
    p.add_argument("--port", type=int, default=0)
    args = p.parse_args(argv)

    home = prepare_home(app_home())
    os.environ["BRANDOPS_HOME"] = str(home)  # must be set before the app modules are imported
    os.environ["BRANDOPS_DESKTOP"] = "1"
    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "sqlite:///" + str(home / "brandops.db")
    from app import server

    if args.demo:
        server.enable_demo()
    port = args.port or free_port()
    srv = server.make_server(port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    wait_ready(url)
    print(f"Brand operations running at {url}\nData folder: {home}", flush=True)
    try:
        wv = None if (args.browser or args.headless) else _webview()
        if wv:
            try:
                wv.create_window("Brand operations", url, width=1280, height=840, min_size=(900, 600))
                wv.start()
                return
            except Exception as e:
                print(f"Native window unavailable ({e}); opening your browser instead.", flush=True)
        if not args.headless:
            webbrowser.open(url)
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()


if __name__ == "__main__":
    main()
