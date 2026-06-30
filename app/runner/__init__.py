"""Test-framework detection, test execution (inside sandbox), output +
stack-trace parsing (Phase 2+).

Reads untrusted workspace content. Produces structured ``{file, line, function}``
frames from stack traces.
"""
