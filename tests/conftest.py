import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="lst_test_")
os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"]
