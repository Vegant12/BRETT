"""Hevy API integration (HEVY-05).

Everything that knows Hevy's wire format lives here and nowhere else. Hevy's own API preamble
says: "we make no guarantees that we won't completely change the structure or abandon the
project entirely so use it at your own risk." That is the whole justification for this
boundary -- when Hevy changes, exactly one package changes.

Import submodules by full path (``from app.integrations.hevy.client import HevyClient``).
This file deliberately re-exports nothing.
"""
