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


class Chomp1d(nn.Module):
    """Schneidet die rechtsseitige Kausal-Polsterung wieder ab.

    Eine dilatierte ``Conv1d`` mit ``padding=(kernel-1)*dilation`` haengt
    Samples auf *beiden* Seiten an; nur die linke Polsterung erhaelt die
    Kausalitaet (Output t sieht nur Input <= t). ``chomp`` entfernt die
    ueberzaehligen rechten Samples, sodass die Sequenzlaenge gleich bleibt.
    """

    def __init__(self, chomp: int) -> None:
        super().__init__()
        self.chomp = chomp

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x[..., : -self.chomp] if self.chomp > 0 else x


class TemporalBlock(nn.Module):
    """Zwei dilatierte Kausal-Convs + Residual -- der TCN-Baustein.

    Jede Conv-Stufe: ``Conv1d -> Chomp1d -> BatchNorm1d -> ReLU -> Dropout``.
    BatchNorm (statt der Paper-``weight_norm``) haelt das Netz scale-tolerant,
    sodass das TCN -- wie das CNN -- ohne Per-Session-Z-Score deploybar
    bleibt. Residual ueber eine 1x1-Conv, falls die Kanalzahl wechselt.
    """

    def __init__(
        self,
        n_in: int,
        n_out: int,
        kernel_size: int = 3,
        dilation: int = 1,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        pad = (kernel_size - 1) * dilation
        self.net = nn.Sequential(
            nn.Conv1d(n_in, n_out, kernel_size, padding=pad, dilation=dilation),
            Chomp1d(pad),
            nn.BatchNorm1d(n_out),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Conv1d(n_out, n_out, kernel_size, padding=pad, dilation=dilation),
            Chomp1d(pad),
            nn.BatchNorm1d(n_out),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        # Why: 1x1-Conv gleicht die Kanalzahl fuer die Residual-Addition an;
        # positions-weise, bricht die Kausalitaet nicht.
        self.downsample = (
            nn.Conv1d(n_in, n_out, 1) if n_in != n_out else nn.Identity()
        )
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.relu(self.net(x) + self.downsample(x))


class TCN(nn.Module):
    """Temporal Convolutional Network (Bai et al. 2018), klein gehalten.

    Vier ``TemporalBlock``s mit exponentiell wachsender Dilation
    (1, 2, 4, 8) -> rezeptives Feld ``1 + 2*(k-1)*sum(dilations) = 61``
    Samples bei kernel=3, deckt ein 1-s-Legacy-Fenster (50 Samples) voll ab.
    ``AdaptiveAvgPool1d(1)`` mittelt ueber die (positions-kausale)
    Feature-Map -- sequenzlaengen-unabhaengig wie beim CNN und nutzt auch
    beim 5-s-Fenster den ganzen Kontext. ~6k Parameter.
    """

    def __init__(
        self,
        n_channels: int = 6,
        hidden: int = 16,
        levels: int = 4,
        kernel_size: int = 3,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        blocks = [
            TemporalBlock(
                n_channels if i == 0 else hidden,
                hidden,
                kernel_size,
                dilation=2 ** i,
                dropout=dropout,
            )
            for i in range(levels)
        ]
        self.tcn = nn.Sequential(*blocks)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, 6) -> Conv1d erwartet (batch, channels, seq)
        x = x.transpose(1, 2)
        x = self.tcn(x)
        x = self.pool(x).squeeze(-1)  # (batch, hidden)
        return self.head(x).squeeze(-1)  # (batch,)


class _RNNClassifier(nn.Module):
    """Gemeinsame Basis fuer LSTM/GRU -- ein RNN-Layer, letzter Hidden-State -> FC."""

    def __init__(
        self, rnn_cls: type[nn.RNNBase], n_channels: int = 6, hidden: int = 32
    ) -> None:
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
    """1-Layer-LSTM, hidden=32. ~5k Parameter."""

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
    "tcn": TCN,
}
