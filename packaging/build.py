"""Build the desktop app with PyInstaller and zip it. Run on each operating system you want to support."""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for d in ("build", "dist"):
    shutil.rmtree(ROOT / d, ignore_errors=True)
subprocess.check_call([sys.executable, "-m", "PyInstaller", "brandops.spec", "--noconfirm", "--clean"], cwd=ROOT)
system, dist = platform.system().lower(), ROOT / "dist"
target = dist / f"BrandOps-{system}-{platform.machine().lower()}"
if system == "darwin":  # ditto keeps the .app bundle intact; a plain zip can break it
    subprocess.check_call(["ditto", "-c", "-k", "--keepParent", str(dist / "BrandOps.app"), f"{target}.zip"])
else:
    shutil.make_archive(str(target), "zip", dist, "BrandOps")
print("Built:", f"{target}.zip")
