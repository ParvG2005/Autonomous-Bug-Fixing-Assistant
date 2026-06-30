"""Autonomous bug-fixing assistant.

Top-level package. Each subpackage is a bounded responsibility per
docs/ARCHITECTURE.md §4. The control/execution plane split (§5) is the
load-bearing invariant: only ``app.vcs`` and ``app.core`` ever hold secrets,
and only ``app.vcs`` can write to a remote.
"""

__version__ = "0.1.0"
