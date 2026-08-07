# ui/__init__.py
"""Zerion WebUI — the official adaptive interface for the Zerion Core.

This package IS the default presentation layer: `python main.py` boots it
(the legacy terminal adapter was retired; main.py carries an inline
minimal REPL for UI-less hosts). It's a front-end adapter over the exact
same Core engines as main.py's loop:

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
