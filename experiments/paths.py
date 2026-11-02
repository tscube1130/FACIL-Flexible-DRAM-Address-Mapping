"""Repository paths and optional scratch roots for reproducible reruns."""
from pathlib import Path
import os
ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("FACIL_RESULTS_ROOT", ROOT / "results")).resolve()
TRACES = Path(os.environ.get("FACIL_TRACES_ROOT", ROOT / "traces")).resolve()
SIMULATOR = Path(os.environ.get("FACIL_SIM_BINARY", ROOT / "build/dramsim3main")).resolve()
CONFIG = Path(os.environ.get("FACIL_CONFIG", ROOT / "configs/LPDDR5_6400_APPROX_v1.ini")).resolve()
