"""Drei kleine Sequenz-Modelle fuer die Schreib-Erkennung.

Alle nehmen Input ``(batch, seq_len, 6)`` und geben einen Logit-Vektor
``(batch,)`` zurueck (binaer, vor Sigmoid). Bewusst klein gehalten --
bei N=10 Probanden ist Parameter-Sparsamkeit wichtiger als Kapazitaet.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn


class CNN1D(nn.Module):
    """Zwei Conv-Bloecke + GlobalAvgPool. ~5-7k Parameter.

    ``AdaptiveAvgPool1d(1)`` macht die FC-Schicht sequenzlaengen-unabhaengig:
    dieselbe Klasse laeuft fuer 50- und 250-Sample-Fenster.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.3) -> None:
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
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(32, 1))

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


class TCN6(TCN):
    """TCN mit 6 Dilatations-Ebenen statt 4 -- rezeptives Feld 253 Samples.

    Dilationen 1/2/4/8/16/32 -> ``1 + 2*(k-1)*sum(dilations) = 253`` Samples
    (~5 s @ 50 Hz). Damit integriert die letzte Position das ganze 5-s-Fenster
    in EINE Entscheidung, statt -- wie der 4-Ebenen-TCN (Feld 61 = ~1.2 s) --
    ~250 lokale 1.2-s-Detektionen zu mitteln. Fairer Gegenpart zum
    RF-Feature-Fenster-Sweep (echter Laengs-Kontext statt Prediction-Mittelung)
    auf der 5-s-Decision-Skala. Bleibt mit ~9k Params klein.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels=n_channels, levels=6, dropout=dropout)


class TCN6Wide(TCN):
    """Breiten-Probe zur HP-Studie: hidden 16 -> 32 (~4x Parameter).

    tcn6 ist mit ~9k Params bei ~19k Trainingsfenstern und Train/Test-Gap
    0.012 data-limited, nicht ueberangepasst -- diese Variante testet, ob
    Kapazitaet die Decke hebt. Gleiche Signatur wie TCN6 (dropout-kwarg
    via ``train_deep_loso``).
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels=n_channels, hidden=32, levels=6,
                         dropout=dropout)


class TCN6K5(TCN):
    """Kernel-Probe zur HP-Studie: kernel 3 -> 5.

    Rezeptives Feld ``1 + 2*(k-1)*sum(dilations) = 505`` Samples --
    saturiert das 250er-5-s-Fenster; testet breiteren Kontext pro
    Faltung bei nahezu unveraendertem Parameter-Budget.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels=n_channels, levels=6, kernel_size=5,
                         dropout=dropout)


class _RNNClassifier(nn.Module):
    """Gemeinsame Basis fuer LSTM/GRU -- ein RNN-Layer, letzter Hidden-State -> FC."""

    def __init__(
        self, rnn_cls: type[nn.RNNBase], n_channels: int = 6, hidden: int = 32, dropout: float = 0.3
    ) -> None:
        super().__init__()
        self.rnn = rnn_cls(
            input_size=n_channels, hidden_size=hidden, batch_first=True
        )
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, 6) -- batch_first, kein Transpose noetig.
        out, _ = self.rnn(x)
        last = out[:, -1, :]  # letzter Zeitschritt, (batch, hidden)
        return self.head(last).squeeze(-1)  # (batch,)


class LSTMClassifier(_RNNClassifier):
    """1-Layer-LSTM, hidden=32. ~5k Parameter."""

    def __init__(self, n_channels: int = 6, hidden: int = 32, dropout: float = 0.3) -> None:
        super().__init__(nn.LSTM, n_channels, hidden, dropout)


class GRUClassifier(_RNNClassifier):
    """1-Layer-GRU, hidden=32. ~4k Parameter. Leichteres RNN-Pendant."""

    def __init__(self, n_channels: int = 6, hidden: int = 32, dropout: float = 0.3) -> None:
        super().__init__(nn.GRU, n_channels, hidden, dropout)


class _PositionalEncoding(nn.Module):
    """Sinusoidales Positional-Encoding (Vaswani et al. 2017), forward-only.

    Wird auf die tatsaechliche Sequenzlaenge zugeschnitten -> seq-len-agnostisch
    wie der Rest des Pakets. ``max_len`` deckt das laengste Fenster ab
    (500 Samples = 5 s @ 100 Hz).
    """

    def __init__(self, d_model: int, max_len: int = 600) -> None:
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(max_len).unsqueeze(1).float()
        div = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, d_model)
        return x + self.pe[:, : x.size(1)]


class TransformerClassifier(nn.Module):
    """Kleiner Transformer-Encoder: Input-Projektion + Positional-Encoding +
    2 Encoder-Layer + Mean-Pool ueber die Zeit + Head. Seq-len-agnostisch.

    Bewusst klein gehalten (~18k Params): bei N<=15 ist Parameter-Sparsamkeit
    wichtiger als Kapazitaet, und ein Transformer ist das daten-hungrigste
    Modell des Pakets. Bewusst NICHT in der Nightly-Default-Matrix -- nur als
    Dispatch-Benchmark (siehe scripts/ml/sweep_matrix.py).
    """

    def __init__(
        self,
        n_channels: int = 6,
        d_model: int = 32,
        nhead: int = 4,
        num_layers: int = 2,
        dim_ff: int = 64,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.proj = nn.Linear(n_channels, d_model)
        self.posenc = _PositionalEncoding(d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_ff,
            dropout=dropout, batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=num_layers)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(d_model, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, 6) -- batch_first, kein Transpose noetig.
        x = self.posenc(self.proj(x))
        x = self.encoder(x)          # (batch, seq, d_model)
        x = x.mean(dim=1)            # Mean-Pool ueber die Zeit, (batch, d_model)
        return self.head(x).squeeze(-1)  # (batch,)


MODELS: dict[str, type[nn.Module]] = {
    "cnn": CNN1D,
    "lstm": LSTMClassifier,
    "gru": GRUClassifier,
    "tcn": TCN,
    "tcn6": TCN6,
    "tcn6w32": TCN6Wide,
    "tcn6k5": TCN6K5,
    "transformer": TransformerClassifier,
}
