# Build with: pyinstaller brandops.spec --noconfirm
import os
import sys

sys.path.insert(0, os.path.abspath(SPECPATH))  # so collect_submodules can import the project's packages
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("connectors") + collect_submodules("app") + ["yaml"]
a = Analysis(
    ["brandops_desktop.py"],
    pathex=["."],
    datas=[("app/static", "app/static"), ("config", "config")],
    hiddenimports=hidden,
    excludes=["google", "psycopg", "psycopg_binary", "tkinter"],  # desktop build: SQLite only, no GA4 API
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BrandOps", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="BrandOps")
app = BUNDLE(coll, name="BrandOps.app", bundle_identifier="app.brandops.desktop")  # macOS only
