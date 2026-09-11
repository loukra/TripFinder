"""Web search providers — how discovery finds thread addresses (plan §2.11).

A sibling of ``ai/`` and for the same reason: one port in ``domain/ports.py``,
several implementations here, and a factory that defaults to the fake so no
process reaches a paid service without an explicit opt-in.
"""
