"""Adapter bridge: ETH Zürich foreign datasets (data/foreign_data/) → our
watch/pen CSV schema (src/server/config.WATCH_FIELDNAMES, src/pen_schema.PEN_FIELDNAMES).

Kept outside src/ on purpose — this is a one-off ingestion bridge for
externally supplied data, not part of the canonical capture pipeline.
See build.py for the entry point.
"""
