"""Load the core IDA/runtime fixtures for extension-owned system tests."""

from __future__ import annotations

# The Docker runner mounts the core checkout at /work and the extension at
# /opt/d810-egglog.  Keep the runner generic: extension tests declare the
# provider-neutral IDA bootstrap and runtime fixtures they consume here.
pytest_plugins = (
    "tests.system.conftest",
    "tests.system.runtime.conftest",
)
