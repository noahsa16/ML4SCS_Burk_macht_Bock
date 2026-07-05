"""Per-Epoch-History-Sink fuer den Event-Bus (Grid-Search-Zwischenstaende).

Konsumiert FOLD_START (haelt die held_out-Kennung) + EPOCH (schreibt eine
Zeile) aus src.training.events; alle anderen Event-Typen werden ignoriert.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

from src.training import events as _events

HISTORY_COLUMNS = ["model", "cfg_id", "seed", "held_out", "epoch",
                   "lr", "train_loss", "val_loss", "val_acc", "val_auc"]


def epoch_history_sink(
    csv_path: Path, model: str, cfg_id: str, seed: int, lr: float
) -> Callable[[dict], None]:
    # Why: Modus "w" -- ein Rerun nach Abbruch ueberschreibt seine
    # partielle History statt zu doppeln (Resume-Einheit = ganzer Trial).
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fh = csv_path.open("w", newline="")
    writer = csv.writer(fh)
    writer.writerow(HISTORY_COLUMNS)
    fh.flush()
    state = {"held_out": ""}

    def _sink(event: dict) -> None:
        etype = event.get("type")
        if etype == _events.FOLD_START:
            state["held_out"] = str(event.get("person", ""))
        elif etype == _events.EPOCH:
            writer.writerow([
                model, cfg_id, seed, state["held_out"], event["epoch"], lr,
                event["loss"], event.get("val_loss", ""),
                event.get("val_acc", ""), event["val_auc"],
            ])
            fh.flush()

    return _sink


def tee(*callbacks: Callable[[dict], None]) -> Callable[[dict], None]:
    def _fanout(event: dict) -> None:
        for cb in callbacks:
            cb(event)
    return _fanout
