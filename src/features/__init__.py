"""ML-Feature-Engineering — *noch leer*.

Hier kommen später die Modell-Inputs rein, die auf dem gemergten Datensatz
aufbauen: Window-Statistics auf IMU (mean/std/min/max pro 0.5-s-Fenster),
Gradients, FFT-Bins, Stroke-Aggregation usw.

Aktueller Status
----------------
Alles, was heute "feature-haft" ist (distance, speed, label_writing pro
Pen-Sample), passiert direkt im Merge-Schritt — siehe
:mod:`src.merge.prep`. Das ist *Daten-Aufbereitung*, kein
Feature-Engineering im ML-Sinn.

TODO (wenn der Datensatz steht)
-------------------------------
* Sliding-Window-Stats auf ax/ay/az/rx/ry/rz
* Spektrale Features (dominante Frequenz, Power-Bands)
* Stroke-Level-Features (Stroke-Dauer, mittlere Beschleunigung pro Stroke)
"""
