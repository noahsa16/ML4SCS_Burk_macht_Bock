"""Drei kleine Sequenz-Modelle fuer die Schreib-Erkennung.

Alle nehmen Input ``(batch, seq_len, 6)`` und geben einen Logit-Vektor
``(batch,)`` zurueck (binaer, vor Sigmoid). Bewusst klein gehalten --
bei N=10 Probanden ist Parameter-Sparsamkeit wichtiger als Kapazitaet.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class CNN1D(nn.Module):
    """Zwei Conv-Bloecke + GlobalAvgPool. ~5-7k Parameter.

    ``AdaptiveAvgPool1d(1)`` macht die FC-Schicht sequenzlaengen-unabhaengig:
    dieselbe Klasse laeuft fuer 50- und 250-Sample-Fenster.
    """

    def __init__(self, n_channels: int = 6) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(n_channels, 16, kernel_size=5, padding=2),
            nn.BatchNorm1d(16),
            nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(16, 32, kernel_size=5, padding=2),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(2),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(32, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, 6) -> Conv1d erwartet (batch, channels, seq)
        x = x.transpose(1, 2)
        x = self.features(x)
        x = self.pool(x).squeeze(-1)  # (batch, 32)
        return self.head(x).squeeze(-1)  # (batch,)


class _RNNClassifier(nn.Module):
    """Gemeinsame Basis fuer LSTM/GRU -- ein RNN-Layer, letzter Hidden-State -> FC."""

    def __init__(self, rnn_cls, n_channels: int = 6, hidden: int = 32) -> None:
        super().__init__()
        self.rnn = rnn_cls(
            input_size=n_channels, hidden_size=hidden, batch_first=True
        )
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, 6) -- batch_first, kein Transpose noetig.
        out, _ = self.rnn(x)
        last = out[:, -1, :]  # letzter Zeitschritt, (batch, hidden)
        return self.head(last).squeeze(-1)  # (batch,)


class LSTMClassifier(_RNNClassifier):
    """1-Layer-LSTM, hidden=32. ~5k Parameter. Funks RNN-Wunsch."""

    def __init__(self, n_channels: int = 6, hidden: int = 32) -> None:
        super().__init__(nn.LSTM, n_channels, hidden)


class GRUClassifier(_RNNClassifier):
    """1-Layer-GRU, hidden=32. ~4k Parameter. Leichteres RNN-Pendant."""

    def __init__(self, n_channels: int = 6, hidden: int = 32) -> None:
        super().__init__(nn.GRU, n_channels, hidden)


MODELS: dict[str, type[nn.Module]] = {
    "cnn": CNN1D,
    "lstm": LSTMClassifier,
    "gru": GRUClassifier,
}
