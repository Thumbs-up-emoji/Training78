"""Streamlit entrypoint (in ``entrypoints/``) for the Milestone-5 monitoring
dashboard.

Run with: ``streamlit run entrypoints/milestone5_dashboard.py --server.port 8502``

Reads ``logs/spans.jsonl`` and ``logs/feedback.jsonl`` (produced by
``entrypoints/milestone5_production_api.py``) via the pure functions in
``app/ops/dashboard_data.py``. See ``app/production_dashboard.py`` for the
actual dashboard implementation -- this file only re-exercises it as a
top-level script, since ``streamlit run`` executes its target file directly
rather than importing it as a module.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_MODULE_NAME = "app.production_dashboard"

# See milestone5_production_ui.py for why a plain `import` is insufficient:
# Streamlit re-executes this script on every rerun, but Python only executes
# a module's top-level code on its *first* import per process.
if _MODULE_NAME in sys.modules:
    importlib.reload(sys.modules[_MODULE_NAME])
else:
    importlib.import_module(_MODULE_NAME)
