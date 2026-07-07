"""Drei kleine Sequenz-Modelle fuer die Schreib-Erkennung.

Alle nehmen Input ``(batch, seq_len, 6)`` und geben einen Logit-Vektor
``(batch,)`` zurueck (binaer, vor Sigmoid). Bewusst klein gehalten --
bei N=10 Probanden ist Parameter-Sparsamkeit wichtiger als Kapazitaet.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn
from torch.nn.utils.parametrizations import weight_norm


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
        norm: str = "batch",
    ) -> None:
        super().__init__()
        pad = (kernel_size - 1) * dilation
        # Why: norm="weight" = Bai-et-al.-Originalrezept (weight_norm auf den
        # Convs, keine Aktivierungs-Normalisierung) -- verliert die
        # BatchNorm-Scale-Toleranz, daher nur als explizite HP-Studien-Probe;
        # Default "batch" bleibt bit-identisch zu allen bisherigen Laeufen.
        if norm == "weight":
            _conv = lambda i, o: weight_norm(  # noqa: E731
                nn.Conv1d(i, o, kernel_size, padding=pad, dilation=dilation))
            _norm = nn.Identity
        else:
            _conv = lambda i, o: nn.Conv1d(  # noqa: E731
                i, o, kernel_size, padding=pad, dilation=dilation)
            _norm = lambda: nn.BatchNorm1d(n_out)  # noqa: E731
        self.net = nn.Sequential(
            _conv(n_in, n_out),
            Chomp1d(pad),
            _norm(),
            nn.ReLU(),
            nn.Dropout(dropout),
            _conv(n_out, n_out),
            Chomp1d(pad),
            _norm(),
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


def _build_tcn_trunk(
    n_channels: int,
    hidden: int,
    levels: int,
    kernel_size: int = 3,
    dropout: float = 0.2,
    norm: str = "batch",
) -> nn.Sequential:
    """Baut den dilatierten TemporalBlock-Stack -- geteilt von TCN und den
    Hybrid-Modellen (TCNGRUHybrid, TCNTransformerHybrid), die den Trunk ohne
    Pooling/Head weiterverwenden."""
    return nn.Sequential(*[
        TemporalBlock(
            n_channels if i == 0 else hidden,
            hidden,
            kernel_size,
            dilation=2 ** i,
            dropout=dropout,
            norm=norm,
        )
        for i in range(levels)
    ])


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
        norm: str = "batch",
    ) -> None:
        super().__init__()
        self.tcn = _build_tcn_trunk(n_channels, hidden, levels, kernel_size,
                                    dropout, norm)
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


class AttnPool1d(nn.Module):
    """Gelerntes Attention-Pooling ueber die Zeitachse.

    Softmax-gewichtete Summe statt uniformem ``AdaptiveAvgPool1d`` --
    das Netz lernt, WELCHE Zeitschritte des Fensters die Entscheidung
    tragen. Rueckgabe ``(batch, hidden, 1)``, drop-in fuer ``self.pool``.
    """

    def __init__(self, hidden: int) -> None:
        super().__init__()
        self.score = nn.Conv1d(hidden, 1, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w = torch.softmax(self.score(x), dim=-1)  # (batch, 1, seq)
        return (x * w).sum(dim=-1, keepdim=True)  # (batch, hidden, 1)


class SEGate(nn.Module):
    """Squeeze-and-Excitation-Gate: kanalweise Sigmoid-Reskalierung.

    Global-Avg ueber die Zeit -> Bottleneck-MLP -> Sigmoid-Gates in (0,1).
    Fensterweit (nutzt die ganze Zeitachse) -- fuer die Fenster-Entscheidung
    unkritisch, bricht aber die Per-Position-Kausalitaet des Conv-Stacks.
    """

    def __init__(self, channels: int, reduction: int = 4) -> None:
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(channels, channels // reduction),
            nn.ReLU(),
            nn.Linear(channels // reduction, channels),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        gates = self.fc(x.mean(dim=-1))  # (batch, channels)
        return x * gates.unsqueeze(-1)


class TCN6WN(TCN):
    """WeightNorm-Probe: Bai-et-al.-Originalrezept statt BatchNorm.

    Verliert die Scale-Toleranz der BatchNorm (siehe TemporalBlock-Note) --
    daher im A/B mit und ohne Per-Session-Z-Score zu testen.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels=n_channels, levels=6, dropout=dropout,
                         norm="weight")


class TCN6AP(TCN):
    """Attention-Pooling-Probe: gewichtetes statt uniformes Zeit-Mittel."""

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels=n_channels, levels=6, dropout=dropout)
        self.pool = AttnPool1d(16)


class TCN6SE(TCN):
    """SE-Probe: Squeeze-and-Excitation-Gate nach jedem TemporalBlock."""

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels=n_channels, levels=6, dropout=dropout)
        gated = []
        for block in self.tcn:
            gated += [block, SEGate(16)]
        self.tcn = nn.Sequential(*gated)


class TCN8(TCN):
    """Tiefen-Probe: 8 Ebenen, Dilationen bis 128 (rezeptives Feld 1021).

    Erwartung laut tcn6-vs-TCN-Befund: kein Gewinn (Feld saturiert das
    250er-Fenster schon bei 6 Ebenen) -- laeuft als Falsifikations-Probe.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels=n_channels, levels=8, dropout=dropout)


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


class GRU2Classifier(nn.Module):
    """2-Layer-GRU (unidirektional), hidden=32. ~11k Parameter.

    Tiefen-Probe gegen den 1-Layer-GRU-Sobol-Ueberraschungssieger (0.9185):
    testet, ob eine zweite rekurrente Ebene ueber den kausalen Verlauf mehr
    Struktur holt. ``dropout`` wirkt zwischen den GRU-Ebenen (PyTorch-Semantik
    bei ``num_layers > 1``) UND im Head.
    """

    def __init__(self, n_channels: int = 6, hidden: int = 32, dropout: float = 0.3) -> None:
        super().__init__()
        self.rnn = nn.GRU(n_channels, hidden, num_layers=2,
                          batch_first=True, dropout=dropout)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.rnn(x)
        return self.head(out[:, -1, :]).squeeze(-1)  # (batch,)


class BiGRUClassifier(nn.Module):
    """Bidirektionaler 1-Layer-GRU, hidden=32 -> 64-dim Repraesentation.

    Fuers 5-s-Fenster als BATCH-Entscheidung legitim (kein Streaming, keine
    Kausalitaets-Pflicht): nutzt Kontext aus beiden Zeitrichtungen. Die
    finalen Hidden-States beider Richtungen (Vorwaerts sieht das ganze
    Fenster bis zum Ende, Rueckwaerts vom Ende zum Anfang) werden
    konkateniert -- die textbuch-uebliche biRNN-Sequenz-Repraesentation,
    nicht ``out[:, -1]`` (dessen Rueckwaerts-Teil nur das letzte Sample saehe).
    ~8k Parameter.
    """

    def __init__(self, n_channels: int = 6, hidden: int = 32, dropout: float = 0.3) -> None:
        super().__init__()
        self.rnn = nn.GRU(n_channels, hidden, batch_first=True,
                          bidirectional=True)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(2 * hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, h_n = self.rnn(x)                      # (2, batch, hidden)
        h = torch.cat([h_n[0], h_n[1]], dim=1)    # (batch, 2*hidden)
        return self.head(h).squeeze(-1)           # (batch,)


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


class TransformerP5(nn.Module):
    """Patch-Transformer: Conv1d-Patch-Embedding statt per-Sample-Projektion.

    Why: der rohe Transformer rechnet Attention ueber alle 250 Samples des
    5-s-Fensters -- O(250²) pro Layer, gemessen ~3.5 h pro LOSO-Fold auf
    CI-CPU-Runnern (Runs 28527728688 + 28576694968), jenseits jedes
    Job-Timeouts. 100-ms-Patches (kernel=stride=5 @ 50 Hz) sind das
    Standard-Rezept fuer lange Sensor-Sequenzen (PatchTST): 250 Samples ->
    50 Tokens, Attention 25x billiger, Positional-Encoding zaehlt Patches.
    """

    def __init__(
        self,
        n_channels: int = 6,
        d_model: int = 32,
        nhead: int = 4,
        num_layers: int = 2,
        dim_ff: int = 64,
        dropout: float = 0.2,
        patch: int = 5,
    ) -> None:
        super().__init__()
        self.embed = nn.Conv1d(n_channels, d_model, kernel_size=patch,
                               stride=patch)
        self.posenc = _PositionalEncoding(d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_ff,
            dropout=dropout, batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=num_layers)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(d_model, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # (batch, seq, ch) -> Conv1d erwartet (batch, ch, seq); zurueck als
        # (batch, seq/patch, d_model) fuer den batch_first-Encoder.
        x = self.embed(x.transpose(1, 2)).transpose(1, 2)
        x = self.posenc(x)
        x = self.encoder(x)
        return self.head(x.mean(dim=1)).squeeze(-1)


class TCNGRUHybrid(nn.Module):
    """TCN6-Trunk (ohne Pooling) + GRU ueber die Feature-Sequenz.

    Der TCN-Trunk wirkt als lokaler Filter (dieselben 6 dilatierten
    TemporalBlocks wie TCN6), das GRU modelliert den zeitlichen Verlauf
    ueber die volle Fenster-Sequenz statt sie sofort zu mitteln. GRUs
    kosten O(seq_len) -- kein Downsampling noetig wie beim Attention-basierten
    Hybrid weiter unten.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2,
                 rnn_hidden: int = 32) -> None:
        super().__init__()
        self.trunk = _build_tcn_trunk(n_channels, hidden=16, levels=6,
                                      dropout=dropout)
        self.gru = nn.GRU(input_size=16, hidden_size=rnn_hidden,
                          batch_first=True)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(rnn_hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, 6) -> Conv1d erwartet (batch, channels, seq)
        x = x.transpose(1, 2)
        feat = self.trunk(x).transpose(1, 2)  # (batch, seq, 16)
        out, _ = self.gru(feat)
        last = out[:, -1, :]  # letzter Zeitschritt, (batch, rnn_hidden)
        return self.head(last).squeeze(-1)  # (batch,)


class TCNTransformerHybrid(nn.Module):
    """TCN-Trunk als Patch-Embedder + Transformer-Encoder ueber die Patches.

    Wie TransformerP5 (100-ms-Patches statt Roh-Samples, Attention 25x
    billiger als ueber alle 250 Samples), aber die Patch-Embeddings kommen
    von einem echten 3-Ebenen-TCN (Dilationen 1/2/4, 29 Samples rezeptives
    Feld pro Token) statt einer einzelnen Conv1d -- lokal informierte
    Patches statt Roh-Sample-Mittel.
    """

    def __init__(self, n_channels: int = 6, d_model: int = 32, nhead: int = 4,
                 num_layers: int = 2, dim_ff: int = 64, dropout: float = 0.2,
                 patch: int = 5) -> None:
        super().__init__()
        self.trunk = _build_tcn_trunk(n_channels, hidden=16, levels=3,
                                      dropout=dropout)
        self.downsample = nn.MaxPool1d(patch)
        self.proj = nn.Conv1d(16, d_model, kernel_size=1)
        self.posenc = _PositionalEncoding(d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_ff,
            dropout=dropout, batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=num_layers)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(d_model, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.transpose(1, 2)                        # (batch, 6, seq)
        x = self.downsample(self.trunk(x))            # (batch, 16, seq/patch)
        x = self.proj(x).transpose(1, 2)               # (batch, seq/patch, d_model)
        x = self.posenc(x)
        x = self.encoder(x)
        return self.head(x.mean(dim=1)).squeeze(-1)


class TCNBiGRUHybrid(nn.Module):
    """TCN6-Trunk (ohne Pooling) + BIDIREKTIONALER GRU ueber die Feature-Sequenz.

    Einzel-Variablen-Delta zu TCNGRUHybrid (dem Front-Runner): der GRU liest die
    Sequenz vorwaerts UND rueckwaerts. Bei der Batch-Klassifikation eines ganzen
    5-s-Fensters ist das zulaessig (kein Online-Streaming innerhalb des Fensters)
    und der Rueckwaerts-Pass traegt Ende-Information -- z. B. das Absetzen des
    Stifts -- in die Repraesentation frueher Zeitschritte. Repraesentation =
    Konkatenation der beiden FINALEN Hidden-States (vorwaerts ``h_n[0]``,
    rueckwaerts ``h_n[1]``), nicht ``out[:, -1, :]`` -- dessen Rueckwaerts-Anteil
    saehe nur das letzte Sample. ~19k Parameter.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2,
                 rnn_hidden: int = 32, trunk_hidden: int = 16) -> None:
        super().__init__()
        # trunk_hidden fliesst konsistent in Trunk-Breite UND GRU.input_size --
        # Default 16 ist bit-identisch zur urspruenglichen fixen Verdrahtung.
        self.trunk = _build_tcn_trunk(n_channels, hidden=trunk_hidden, levels=6,
                                      dropout=dropout)
        self.gru = nn.GRU(input_size=trunk_hidden, hidden_size=rnn_hidden,
                          batch_first=True, bidirectional=True)
        self.head = nn.Sequential(nn.Dropout(dropout),
                                  nn.Linear(2 * rnn_hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.transpose(1, 2)
        feat = self.trunk(x).transpose(1, 2)      # (batch, seq, trunk_hidden)
        _, h_n = self.gru(feat)                   # (2, batch, rnn_hidden)
        h = torch.cat([h_n[0], h_n[1]], dim=1)    # (batch, 2*rnn_hidden)
        return self.head(h).squeeze(-1)


class TCNBiGRUWide32_24(TCNBiGRUHybrid):
    """tcn_bigru mit breiterem Trunk (16->24), GRU unveraendert (32) -- die
    Trunk-Kapazitaets-Achse isoliert (Blocker-A-Kapazitaets-Probe)."""

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels, dropout, rnn_hidden=32, trunk_hidden=24)


class TCNBiGRUWide64_16(TCNBiGRUHybrid):
    """tcn_bigru mit breiterem GRU (32->64), Trunk unveraendert (16) -- die
    Rekurrenz-Kapazitaets-Achse isoliert."""

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels, dropout, rnn_hidden=64, trunk_hidden=16)


class TCNBiGRUWide64_24(TCNBiGRUHybrid):
    """tcn_bigru breit auf beiden Achsen (Trunk 24, GRU 64)."""

    def __init__(self, n_channels: int = 6, dropout: float = 0.2) -> None:
        super().__init__(n_channels, dropout, rnn_hidden=64, trunk_hidden=24)


class TCNGRUAttnHybrid(nn.Module):
    """TCN6-Trunk + GRU, aber Attention-Pooling ueber ALLE GRU-Outputs statt nur
    des letzten Hidden-State.

    Einzel-Variablen-Delta zu TCNGRUHybrid: statt ``out[:, -1, :]`` gewichtet ein
    gelerntes ``AttnPool1d`` (Softmax ueber die Zeit) alle GRU-Ausgaben. Das Netz
    lernt selbst, welche Fenster-Abschnitte die Schreib-Entscheidung tragen --
    nuetzlich, falls der Gate-Mechanismus ueber 250 Schritte Ende-lastig
    vergisst. Fenster-weit (nutzt die Zukunft) -- fuer die Batch-Fenster-
    Entscheidung zulaessig, nicht kausal streambar. ~14k Parameter.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2,
                 rnn_hidden: int = 32) -> None:
        super().__init__()
        self.trunk = _build_tcn_trunk(n_channels, hidden=16, levels=6,
                                      dropout=dropout)
        self.gru = nn.GRU(input_size=16, hidden_size=rnn_hidden,
                          batch_first=True)
        self.pool = AttnPool1d(rnn_hidden)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(rnn_hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.transpose(1, 2)
        feat = self.trunk(x).transpose(1, 2)         # (batch, seq, 16)
        out, _ = self.gru(feat)                      # (batch, seq, rnn_hidden)
        pooled = self.pool(out.transpose(1, 2))      # (batch, rnn_hidden, 1)
        return self.head(pooled.squeeze(-1)).squeeze(-1)


class TCNBiGRUAttnHybrid(nn.Module):
    """TCN6-Trunk + BIDIREKTIONALER GRU + Attention-Pooling ueber alle Outputs.

    Kreuzung der beiden Einzel-Deltas: bidirektionaler GRU-Head (wie
    ``TCNBiGRUHybrid`` -- liest vorwaerts UND rueckwaerts) UND gelerntes
    Attention-Pooling ueber die gesamte Ausgabesequenz (wie ``TCNGRUAttnHybrid``
    -- statt nur der finalen Hidden-States). Ein bidirektionaler GRU liefert pro
    Zeitschritt ``2*rnn_hidden`` Kanaele (Vorwaerts+Rueckwaerts konkateniert),
    also poolt ``AttnPool1d`` ueber ``2*rnn_hidden``: das Netz waehlt selbst die
    entscheidungstragenden Zeitschritte UND sieht an jeder Position beide
    Zeitrichtungen. Fenster-weit (nutzt die Zukunft), fuer die Batch-Fenster-
    Entscheidung zulaessig, nicht kausal streambar. ~19k Parameter.
    """

    def __init__(self, n_channels: int = 6, dropout: float = 0.2,
                 rnn_hidden: int = 32) -> None:
        super().__init__()
        self.trunk = _build_tcn_trunk(n_channels, hidden=16, levels=6,
                                      dropout=dropout)
        self.gru = nn.GRU(input_size=16, hidden_size=rnn_hidden,
                          batch_first=True, bidirectional=True)
        self.pool = AttnPool1d(2 * rnn_hidden)
        self.head = nn.Sequential(nn.Dropout(dropout),
                                  nn.Linear(2 * rnn_hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.transpose(1, 2)
        feat = self.trunk(x).transpose(1, 2)      # (batch, seq, 16)
        out, _ = self.gru(feat)                   # (batch, seq, 2*rnn_hidden)
        pooled = self.pool(out.transpose(1, 2))   # (batch, 2*rnn_hidden, 1)
        return self.head(pooled.squeeze(-1)).squeeze(-1)


class _InceptionModule(nn.Module):
    """Ein Inception-Block (Fawaz et al. 2020): Bottleneck -> parallele Convs
    mehrerer Kernel-Groessen + MaxPool-Zweig -> Concat -> BatchNorm -> ReLU.

    Die parallelen Kernel (9/19/39) sehen kurze bis lange Motive gleichzeitig
    -- der strukturelle Unterschied zum festen 5er-Kernel des einfachen CNN.
    Alle Kernel sind ungerade mit ``padding=k//2`` -> laengen-erhaltend.
    """

    def __init__(self, in_ch: int, n_filters: int = 16,
                 kernel_sizes: tuple[int, ...] = (9, 19, 39),
                 bottleneck: int = 16) -> None:
        super().__init__()
        use_bottleneck = in_ch > 1
        self.bottleneck = (nn.Conv1d(in_ch, bottleneck, 1, bias=False)
                           if use_bottleneck else nn.Identity())
        bch = bottleneck if use_bottleneck else in_ch
        self.convs = nn.ModuleList([
            nn.Conv1d(bch, n_filters, k, padding=k // 2, bias=False)
            for k in kernel_sizes
        ])
        self.maxpool = nn.MaxPool1d(3, stride=1, padding=1)
        self.pool_conv = nn.Conv1d(in_ch, n_filters, 1, bias=False)
        self.bn = nn.BatchNorm1d(n_filters * (len(kernel_sizes) + 1))
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b = self.bottleneck(x)
        outs = [conv(b) for conv in self.convs]
        outs.append(self.pool_conv(self.maxpool(x)))
        return self.relu(self.bn(torch.cat(outs, dim=1)))


class InceptionTime(nn.Module):
    """InceptionTime (Fawaz et al. 2020) -- Multi-Scale-CNN, TSC-Benchmark-
    Sieger. 6 Inception-Bloecke, Residual alle 3 Bloecke, GlobalAvgPool -> FC.

    Groesser als der Rest des Zoos (~110k Params, vs ~10k), aber absolut klein
    -- der bewusst staerkere CNN-Gegenpart zum bei 0.897 gedeckelten einfachen
    CNN. ``AdaptiveAvgPool1d(1)`` macht ihn sequenzlaengen-agnostisch wie CNN/TCN.
    """

    def __init__(self, n_channels: int = 6, n_filters: int = 16,
                 depth: int = 6, dropout: float = 0.2) -> None:
        super().__init__()
        out_ch = n_filters * 4  # 3 Kernel-Zweige + 1 Pool-Zweig
        self.blocks = nn.ModuleList()
        # Why: ModuleDict statt ModuleList-mit-None -- ModuleList darf keine
        # None-Eintraege tragen; Residual gibt es nur alle 3 Bloecke.
        self.residuals = nn.ModuleDict()
        in_ch = n_channels
        res_in = n_channels
        for d in range(depth):
            self.blocks.append(_InceptionModule(in_ch, n_filters))
            in_ch = out_ch
            if d % 3 == 2:
                self.residuals[str(d)] = nn.Sequential(
                    nn.Conv1d(res_in, out_ch, 1, bias=False),
                    nn.BatchNorm1d(out_ch),
                )
                res_in = out_ch
        self.gap = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(out_ch, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.transpose(1, 2)  # (batch, seq, 6) -> (batch, 6, seq)
        res = x
        out = x
        for d, block in enumerate(self.blocks):
            out = block(out)
            if str(d) in self.residuals:
                out = torch.relu(out + self.residuals[str(d)](res))
                res = out
        out = self.gap(out).squeeze(-1)  # (batch, out_ch)
        return self.head(out).squeeze(-1)  # (batch,)


MODELS: dict[str, type[nn.Module]] = {
    "cnn": CNN1D,
    "lstm": LSTMClassifier,
    "gru": GRUClassifier,
    "gru2": GRU2Classifier,
    "bigru": BiGRUClassifier,
    "inception": InceptionTime,
    "tcn": TCN,
    "tcn6": TCN6,
    "tcn6w32": TCN6Wide,
    "tcn6k5": TCN6K5,
    "tcn6wn": TCN6WN,
    "tcn6ap": TCN6AP,
    "tcn6se": TCN6SE,
    "tcn8": TCN8,
    "transformer": TransformerClassifier,
    "transformer_p5": TransformerP5,
    "tcn_gru": TCNGRUHybrid,
    "tcn_bigru": TCNBiGRUHybrid,
    "tcn_gru_attn": TCNGRUAttnHybrid,
    "tcn_bigru_attn": TCNBiGRUAttnHybrid,
    "tcn_transformer": TCNTransformerHybrid,
    "tcn_bigru_w32_24": TCNBiGRUWide32_24,
    "tcn_bigru_w64_16": TCNBiGRUWide64_16,
    "tcn_bigru_w64_24": TCNBiGRUWide64_24,
}
