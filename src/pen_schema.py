"""
Shared pen CSV schema — imported by both pen_logger.py and src/server/config.py.
No dependencies so pen_logger.py can remain a standalone script.
"""

PEN_FIELDNAMES = [
    "local_ts", "local_ts_ms",
    "timestamp", "x", "y", "pressure", "dot_type",
    "tilt_x", "tilt_y", "section", "owner", "note", "page",
]
