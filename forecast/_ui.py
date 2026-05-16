"""Mission-control TUI for the learning-curve forecast.

Provides a boot sequence, a live multi-panel dashboard (results table +
current-job panel + live plotext chart + progress bar) and an animated
finale that reveals the per-model asymptotes.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import numpy as np
import plotext as plt
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn,
)
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

CONSOLE = Console()

# Colors mirror the ones in learning_curve.py / compare_runs.py so the
# terminal vibe matches the rendered PNG/HTML.
MODEL_COLORS = {
    "ExtraTrees":    "#5cffb8",
    "RandomForest":  "#7eb8ff",
    "HistGradBoost": "#ffb45c",
    "XGBoost":       "#ff9a4d",
    "LogReg":        "#ff7eb8",
    "DeepMLP":       "#c890ff",
    "1D-CNN":        "#ffd95c",
    "BiLSTM":        "#a8ff5c",
    "Transformer":   "#5ce3ff",
}
ACCENT = "#5cffb8"
DIM = "#5a6877"


def _gradient_text(text: str, start: str = "#5ce3ff", end: str = "#c890ff") -> Text:
    """Two-stop linear gradient across a string."""
    sr, sg, sb = int(start[1:3], 16), int(start[3:5], 16), int(start[5:7], 16)
    er, eg, eb = int(end[1:3], 16), int(end[3:5], 16), int(end[5:7], 16)
    out = Text()
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        t = i / n
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        out.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
    return out


def _typewriter(line: str, delay: float = 0.012, style: str = "white") -> None:
    for ch in line:
        CONSOLE.print(ch, end="", style=style, soft_wrap=True, highlight=False)
        time.sleep(delay)
    CONSOLE.print()


def boot_sequence(persons: list[str], device: str, n_total_fits: int) -> None:
    """Cinema-style startup typewriter."""
    CONSOLE.clear()
    CONSOLE.print()
    CONSOLE.print(Align.center(_gradient_text(
        "ML4SCS  ::  LEARNING CURVE FORECAST", "#5ce3ff", "#c890ff")))
    CONSOLE.print(Align.center(Text(
        "general writing-activity detector  ·  cross-subject LOSO",
        style=f"italic {DIM}")))
    CONSOLE.print()

    lines = [
        ("> initializing forecast pipeline ...",                    "#5cffb8"),
        (f"> scanning data/sessions.csv ............ {len(persons)} subjects",
                                                                    "#7eb8ff"),
        (f"> probands online ........................ {', '.join(persons)}",
                                                                    "#7eb8ff"),
        ("> applying quality gate ................... verdict in {trainable, usable}",
                                                                    "#7eb8ff"),
        ("> excluding study_mode=test ............... OK",          "#7eb8ff"),
        (f"> spinning up classical bank .............. ExtraTrees · RandomForest · HistGradBoost · LogReg",
                                                                    "#ffb45c"),
        (f"> spinning up deep learning architectures . DeepMLP · 1D-CNN · BiLSTM · Transformer",
                                                                    "#c890ff"),
        (f"> torch backend ........................... {device.upper()}",
                                                                    "#c890ff"),
        (f"> total fits scheduled .................... {n_total_fits}",
                                                                    "#ffd95c"),
        ("> handshake complete  ::  GO / NO-GO  ::  GO",            "#5cffb8"),
    ]
    for line, color in lines:
        _typewriter(line, delay=0.006, style=color)
    CONSOLE.print()
    CONSOLE.print(Rule(style=ACCENT))
    time.sleep(0.4)


@dataclass
class _JobState:
    kind: str = ""        # "DL" or "SK"
    n_train: int = 0
    train_combo: tuple[str, ...] = ()
    test_p: str = ""
    model: str = ""
    started: float = 0.0


@dataclass
class _ForecastState:
    persons: list[str] = field(default_factory=list)
    model_order: list[str] = field(default_factory=list)
    n_train_values: list[int] = field(default_factory=list)
    # results[model][n_train] -> list of acc values across folds
    results: dict[str, dict[int, list[float]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list)))
    aucs: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    current: _JobState = field(default_factory=_JobState)
    done: int = 0
    total: int = 0


class ForecastUI:
    """Rich Live dashboard. Use as a context manager."""

    def __init__(self, persons: list[str], model_order: list[str],
                 n_train_values: list[int], total_fits: int):
        self.state = _ForecastState(
            persons=persons, model_order=model_order,
            n_train_values=n_train_values, total=total_fits,
        )
        self._layout = self._build_layout()
        self._live = Live(
            self._layout, console=CONSOLE,
            refresh_per_second=8, transient=False, screen=False,
        )
        self._spinner = Spinner("dots12", text="", style=ACCENT)

    # --- public API -------------------------------------------------

    def __enter__(self):
        self._live.__enter__()
        self._refresh()
        return self

    def __exit__(self, *exc):
        self._live.__exit__(*exc)

    def start_job(self, kind: str, n_train: int, train_combo: tuple,
                  test_p: str, model: str) -> None:
        self.state.current = _JobState(
            kind=kind, n_train=n_train, train_combo=train_combo,
            test_p=test_p, model=model, started=time.time(),
        )
        self._refresh()

    def finish_job(self, acc: float, auc: float | None) -> None:
        cur = self.state.current
        self.state.results[cur.model][cur.n_train].append(acc)
        if auc is not None and not np.isnan(auc):
            self.state.aucs[cur.model].append(auc)
        self.state.done += 1
        self._refresh()

    # --- layout primitives ------------------------------------------

    def _build_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="upper", ratio=1),
            Layout(name="chart", ratio=1),
            Layout(name="footer", size=3),
        )
        layout["upper"].split_row(
            Layout(name="table", ratio=3),
            Layout(name="job", ratio=2),
        )
        return layout

    def _refresh(self) -> None:
        self._layout["header"].update(self._render_header())
        self._layout["table"].update(self._render_table())
        self._layout["job"].update(self._render_job())
        self._layout["chart"].update(self._render_chart())
        self._layout["footer"].update(self._render_footer())

    # --- panels ------------------------------------------------------

    def _render_header(self) -> Panel:
        title = _gradient_text(
            "  ML4SCS  ::  LEARNING CURVE FORECAST  ", "#5ce3ff", "#c890ff")
        sub = Text(
            f"N={len(self.state.persons)} probands  ·  "
            f"{datetime.now().strftime('%H:%M:%S')}  ·  cross-subject LOSO",
            style=f"italic {DIM}",
        )
        return Panel(Align.center(Group(title, sub)),
                     border_style=ACCENT, padding=(0, 1))

    def _render_table(self) -> Panel:
        s = self.state
        tbl = Table(
            show_header=True, header_style=f"bold {ACCENT}",
            border_style=DIM, expand=True, pad_edge=False,
        )
        tbl.add_column("Modell", style="bold", no_wrap=True)
        for n in s.n_train_values:
            tbl.add_column(f"n={n}", justify="center", no_wrap=True)
        tbl.add_column("mean", justify="center", style=f"bold {ACCENT}")
        tbl.add_column("AUC", justify="center", style="bold")

        for model in s.model_order:
            color = MODEL_COLORS.get(model, "#cccccc")
            row = [Text(model, style=f"bold {color}")]
            all_means = []
            for n in s.n_train_values:
                vals = s.results[model].get(n, [])
                if not vals:
                    row.append(Text("─", style=DIM))
                else:
                    mean = float(np.mean(vals))
                    all_means.append(mean)
                    row.append(Text(f"{mean:.3f}", style=color))
            if all_means:
                row.append(Text(f"{np.mean(all_means):.3f}", style=f"bold {color}"))
            else:
                row.append(Text("─", style=DIM))
            aucs = s.aucs.get(model, [])
            row.append(Text(f"{np.mean(aucs):.3f}" if aucs else "─",
                            style=color if aucs else DIM))
            tbl.add_row(*row)

        return Panel(tbl, title="[bold]Live Results[/]",
                     border_style=ACCENT, padding=(0, 1))

    def _render_job(self) -> Panel:
        cur = self.state.current
        if not cur.model:
            body = Align.center(Text("idle ...", style=DIM))
            return Panel(body, title="[bold]Current Fit[/]",
                         border_style=DIM, padding=(1, 1))

        elapsed = time.time() - cur.started
        color = MODEL_COLORS.get(cur.model, "#cccccc")
        kind_badge = ("DL " if cur.kind == "DL" else "SK ")
        kind_style = "#c890ff" if cur.kind == "DL" else "#ffb45c"

        body = Group(
            Text(f"[ {kind_badge} ]   ", style=f"bold {kind_style}",
                 end="").append(cur.model, style=f"bold {color}"),
            Text(),
            Text(f"  n_train = {cur.n_train}", style="white"),
            Text(f"  train   = {' + '.join(cur.train_combo)}",
                 style=f"italic {DIM}"),
            Text(f"  test    = {cur.test_p}", style=f"italic {color}"),
            Text(),
            self._spinner.render(time.time()),
            Text(f"  elapsed {elapsed:5.1f}s", style=DIM),
        )
        return Panel(body, title="[bold]Current Fit[/]",
                     border_style=color, padding=(1, 2))

    def _render_chart(self) -> Panel:
        s = self.state
        from forecast._stats import fit_power_law, _power

        chart_w = max(CONSOLE.width - 8, 60)
        chart_h = 18
        plt.clf()
        plt.theme("dark")
        plt.plotsize(chart_w, chart_h)
        plt.canvas_color("default")
        plt.axes_color("default")
        plt.ticks_color("white")

        # Build a smooth n-grid; we always show 1..50 so the asymptote
        # is visible from the moment data appears.
        n_grid = np.logspace(np.log10(1), np.log10(50), 120)

        active_models: list[tuple[str, str, float | None]] = []  # (name, color, asymptote)
        for model in s.model_order:
            xs, ys = [], []
            for n in s.n_train_values:
                vals = s.results[model].get(n, [])
                if vals:
                    xs.append(n)
                    ys.append(float(np.mean(vals)))
            if len(xs) < 1:
                continue
            color = MODEL_COLORS.get(model, "#cccccc")
            rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))

            asym: float | None = None
            if len(xs) >= 2:
                fit = fit_power_law(np.asarray(xs, float),
                                    np.asarray(ys, float))
                if fit is not None:
                    c, a, b = fit
                    ys_curve = _power(n_grid, c, a, b)
                    plt.plot(n_grid.tolist(), ys_curve.tolist(),
                             color=rgb, marker="hd")
                    asym = float(c)
            # Always overlay the empirical means as bigger braille markers
            plt.scatter(xs, ys, color=rgb, marker="braille")
            active_models.append((model, color, asym))

        if not active_models:
            body = Align.center(Text(
                "⠁⠂⠄  awaiting first measurements  ⠄⠂⠁",
                style=f"italic {DIM}"))
            return Panel(body, title="[bold]Live Power-Law Fits[/]",
                         border_style=DIM, padding=(1, 1))

        plt.ylim(0.45, 1.0)
        plt.xlim(0.9, 52)
        plt.xticks([1, 2, 3, 5, 10, 20, 30, 50])
        plt.xlabel("n_train  (probands in pool)")
        plt.ylabel("accuracy")
        chart_str = plt.build()

        # Custom legend strip showing per-model live asymptote estimate
        legend = Text()
        for i, (name, color, asym) in enumerate(active_models):
            if i and i % 4 == 0:
                legend.append("\n")
            asym_txt = f"C={asym:.3f}" if asym is not None else "C=─"
            legend.append("  ●", style=color)
            legend.append(f" {name:<14}", style=f"bold {color}")
            legend.append(f" {asym_txt}  ", style=DIM)

        body = Group(
            Text.from_ansi(chart_str),
            Rule(style=DIM),
            legend,
        )

        title = (f"[bold]Live Power-Law Fits[/]   "
                 f"[dim]curves materialize as each model accumulates ≥2 n_train points;"
                 f" C = asymptote estimate[/]")
        return Panel(body, title=title,
                     border_style=ACCENT, padding=(0, 1))

    def _render_footer(self) -> Panel:
        s = self.state
        pct = (s.done / s.total) if s.total else 0
        bar_width = max(CONSOLE.width - 40, 20)
        filled = int(bar_width * pct)
        bar = Text()
        bar.append("█" * filled, style=ACCENT)
        bar.append("░" * (bar_width - filled), style=DIM)

        eta_s = ""
        if s.done > 0 and s.current.started > 0:
            # crude ETA: average elapsed per fit so far (best effort)
            elapsed = time.time() - s.current.started + 0.001
            per_fit = elapsed if s.done == 1 else None
            # Not great — fall back to "~"
            pass

        info = Text()
        info.append(f"{s.done:>3d} / {s.total}  ", style=f"bold {ACCENT}")
        info.append("fits   ", style=DIM)
        info.append(f"{pct*100:5.1f}%", style="bold white")
        line = Text("  ")
        line.append(bar)
        line.append("  ")
        line.append(info)
        return Panel(line, border_style=DIM, padding=(0, 1))


def reveal_finale(forecasts: dict[str, tuple[float, float, float]],
                  forecast_n: list[int],
                  validation: dict[str, dict] | None = None) -> None:
    """Animated score-counter reveal of each model's extrapolated asymptote.

    If ``validation`` is provided, prints a second panel after the
    asymptote table:
      validation[model] = {
        "ci_lo": float,   # 5%ile asymptote across bootstrap samples
        "ci_hi": float,   # 95%ile
        "loso_mae": float,  # mean abs error of LOSO curve-fit validation
        "best_alt": str,    # name of lowest-RSS alternative
        "best_rss": float,
        "pow_rss": float,   # power-law RSS for comparison
      }
    """
    CONSOLE.print()
    CONSOLE.print(Rule(_gradient_text("  ::  FORECAST COMPLETE  ::  ",
                                      "#5cffb8", "#5ce3ff"),
                       style=ACCENT))
    CONSOLE.print()

    def _power(n, c, a, b):
        return c - a * np.power(n, -b)

    # Animate: count C up over ~0.8s per model
    items = list(forecasts.items())
    steps = 24
    duration = 0.8

    tbl = Table(
        show_header=True, header_style=f"bold {ACCENT}",
        border_style=ACCENT, expand=False, title_style=ACCENT,
        title="extrapolated asymptote  ::  acc(n→∞)  and forecast curve",
    )
    tbl.add_column("Modell", style="bold")
    tbl.add_column("C  (asymptote)", justify="center")
    for n in forecast_n:
        tbl.add_column(f"n={n}", justify="center")

    with Live(tbl, console=CONSOLE, refresh_per_second=20) as live:
        for name, (c, a, b) in items:
            color = MODEL_COLORS.get(name, "#cccccc")
            for k in range(1, steps + 1):
                t = k / steps
                # ease-out
                ease = 1 - (1 - t) ** 3
                c_partial = c * ease
                vals = [c_partial] + [_power(n, c, a, b) * ease for n in forecast_n]
                # Rebuild table from scratch each tick is simplest; but
                # we want progressive reveal -- so add row on first tick,
                # update on subsequent.  Table doesn't expose row update.
                # Workaround: build a fresh table per tick.
                fresh = Table(
                    show_header=True, header_style=f"bold {ACCENT}",
                    border_style=ACCENT, expand=False, title_style=ACCENT,
                    title="extrapolated asymptote  ::  acc(n→∞)  and forecast curve",
                )
                fresh.add_column("Modell", style="bold")
                fresh.add_column("C  (asymptote)", justify="center")
                for n in forecast_n:
                    fresh.add_column(f"n={n}", justify="center")
                # finalized rows
                for finished_name, (fc, fa, fb) in items[: items.index((name, (c, a, b)))]:
                    fcolor = MODEL_COLORS.get(finished_name, "#cccccc")
                    fvals = [fc] + [_power(n, fc, fa, fb) for n in forecast_n]
                    fresh.add_row(
                        Text(finished_name, style=f"bold {fcolor}"),
                        *[Text(f"{v:.3f}", style=fcolor) for v in fvals],
                    )
                # animating row
                fresh.add_row(
                    Text(name, style=f"bold {color}"),
                    *[Text(f"{v:.3f}", style=color) for v in vals],
                )
                live.update(fresh)
                time.sleep(duration / steps)
        # final pass with all rows committed
        final = Table(
            show_header=True, header_style=f"bold {ACCENT}",
            border_style=ACCENT, expand=False, title_style=ACCENT,
            title="extrapolated asymptote  ::  acc(n→∞)  and forecast curve",
        )
        final.add_column("Modell", style="bold")
        final.add_column("C  (asymptote)", justify="center")
        for n in forecast_n:
            final.add_column(f"n={n}", justify="center")
        for name, (c, a, b) in items:
            color = MODEL_COLORS.get(name, "#cccccc")
            vals = [c] + [_power(n, c, a, b) for n in forecast_n]
            final.add_row(
                Text(name, style=f"bold {color}"),
                *[Text(f"{v:.3f}", style=color) for v in vals],
            )
        live.update(final)
        time.sleep(0.4)

    if validation:
        CONSOLE.print()
        vtbl = Table(
            show_header=True, header_style=f"bold {ACCENT}",
            border_style=ACCENT, expand=False, title_style=ACCENT,
            title="scientific rigor :: 90% bootstrap CI on the asymptote  ·  "
                  "LOSO out-of-sample forecast MAE",
        )
        vtbl.add_column("Modell", style="bold")
        vtbl.add_column("C  (90% CI)", justify="center")
        vtbl.add_column("CI-Breite", justify="center")
        vtbl.add_column("LOSO MAE", justify="center",
                        header_style=f"bold {ACCENT}")
        for name, (c, *_rest) in items:
            v = validation.get(name)
            color = MODEL_COLORS.get(name, "#cccccc")
            if not v:
                vtbl.add_row(Text(name, style=f"bold {color}"),
                             "─", "─", "─")
                continue
            ci_str = (f"[{v['ci_lo']:.3f}, {v['ci_hi']:.3f}]"
                      if not np.isnan(v["ci_lo"]) else "─")
            width = (v["ci_hi"] - v["ci_lo"]
                     if not np.isnan(v["ci_lo"]) else float("nan"))
            width_str = f"{width:.3f}" if not np.isnan(width) else "─"
            width_color = (ACCENT if width < 0.05
                           else "#ffd95c" if width < 0.10
                           else "#ff7eb8")
            mae_str = (f"{v['loso_mae']:.3f}" if not np.isnan(v["loso_mae"])
                       else "─")
            mae_color = (ACCENT if v.get("loso_mae", 1) < 0.05
                         else "#ffd95c" if v.get("loso_mae", 1) < 0.10
                         else "#ff7eb8")
            vtbl.add_row(
                Text(name, style=f"bold {color}"),
                Text(ci_str, style=color),
                Text(width_str, style=f"bold {width_color}"),
                Text(mae_str, style=f"bold {mae_color}"),
            )
        CONSOLE.print(vtbl)

        CONSOLE.print()
        CONSOLE.print(Text(
            "  Hinweis: bei N≤5 Probanden ist jeder Forecast jenseits "
            "n_train>5 mit erheblicher Unsicherheit belegt.\n"
            "  CI-Breite > 0.10 oder LOSO-MAE > 0.10  ⇒  Datenbasis "
            "noch zu klein, Aussagen rein qualitativ behandeln.",
            style=f"italic {DIM}",
        ))

    CONSOLE.print()
    CONSOLE.print(Rule(style=ACCENT))
