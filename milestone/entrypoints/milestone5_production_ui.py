"""Streamlit entrypoint (in ``entrypoints/``) for the Milestone-5 production UI.

Run with: ``streamlit run entrypoints/milestone5_production_ui.py``

Requires ``entrypoints/milestone5_production_api.py`` (or
``app/production_api.py``) to be running separately (default
``http://127.0.0.1:8000``) and ``MILESTONE5_API_KEY`` to be set in the
environment so requests are authenticated. See ``app/production_ui.py`` for
the actual UI implementation -- this file only re-exercises it as a
top-level script, since ``streamlit run`` executes its target file directly
rather than importing it as a module.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_MODULE_NAME = "app.production_ui"

# Streamlit re-executes this top-level script on every rerun (e.g. after a
# form submit), but a plain `import` is only executed once per process --
# subsequent reruns would be a no-op (module already cached in sys.modules),
# silently rendering nothing. Reload on every rerun after the first so
# app/production_ui.py's render() call actually re-runs each time, without
# double-running it on the very first import.
if _MODULE_NAME in sys.modules:
    importlib.reload(sys.modules[_MODULE_NAME])
else:
    importlib.import_module(_MODULE_NAME)
