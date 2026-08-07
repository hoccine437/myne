# ui/__init__.py
"""Zerion WebUI — the official adaptive interface for the Zerion Core.

This package is a *front-end adapter*. It stands next to ``terminal.py``
(and main.py's loop) as an alternative presentation layer over the exact
same Core engines:

    intent.engine, intent.commands, planner, tools.manager, llm,
    knowledge, learning, cognition, capabilities, intelligence,
    constitution, memory ...

Nothing in this package re-implements Core behavior. Session turns run
through the same engines in the same order as ``main.py:run_loop`` — the
only difference is that terminal printing/speaking is replaced by
structured events the web client renders (see ``session.py``'s module
docstring for the mirroring contract).

Run it with:

    python -m ui.server            (from the zerion/ directory, or)
    uvicorn ui.server:app
"""
