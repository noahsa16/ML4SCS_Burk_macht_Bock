"""Modell-Training — *noch leer*.

Hier kommt das eigentliche ML-Training rein: Modell-Definition,
Train/Val-Split, Loss, Optimizer, Checkpoint-Saving.

Hinweis
-------
Die alte ``train.py`` war kein Training, sondern nur ein CLI-Wrapper für
den Merge. Den Merge-Aufruf gibt's jetzt direkt unter::

    python -m src.merge [SESSION]

TODO (wenn Features stehen)
---------------------------
* Train/Val-Split per Session-ID (kein Leakage über Sessions)
* Baseline: Logistic Regression oder Random-Forest auf
  Window-Features → Writing vs. NotWriting
* Konzentrations-Klassifikation als zweiter Schritt
* Evaluation siehe :mod:`src.evaluation`
"""
