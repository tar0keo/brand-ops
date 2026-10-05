"""Where user data lives: BRANDOPS_HOME (set by the desktop app) or, in development, the repo folder."""
import os
from pathlib import Path


def home():
    env = os.environ.get("BRANDOPS_HOME")
    return Path(env) if env else Path(__file__).resolve().parent.parent
