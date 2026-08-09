import os
import sys
from pathlib import Path
import json
import pandas as pd
import subprocess

# Projekt-Root zum Python-Path hinzufügen (Datei liegt in scripts/ml/ → parents[2])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import rich
    import plotext as plt
    import wandb
except ImportError as e:
    print(f"Fehler: Abhängigkeit fehlt ({e}). Bitte installiere sie mit: pip install rich plotext wandb")
    sys.exit(1)

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.live import Live
from rich.text import Text

from src.training.deep.grid import load_grid_spec, grid_outdir, trial_name, _check_or_write_meta
from src.training.deep.hp_search import grid_configs
from src.training.deep.train_loso import train_deep_loso
from src.training.deep.history import epoch_history_sink, tee
from src.training import events as EV

console = Console()


def get_plotext_string(curves, fold, max_epochs):
    """Rendert die Lernkurven mit plotext und gibt das ANSI-Terminalbild als String zurück."""
    plt.clf()
    plt.theme("dark")
    
    pts = curves.get(fold, [])
    if pts:
        epochs, losses, val_losses, val_aucs = zip(*pts)
        plt.plot(epochs, losses, label="Train Loss", color="blue", marker="dot")
        plt.plot(epochs, val_losses, label="Val Loss", color="orange", marker="dot")
        plt.plot(epochs, val_aucs, label="Val AUC", color="green", marker="dot")
    else:
        plt.scatter([0], [0], label="Warte auf Daten...", color="red")
        
    plt.title(f"Lernkurve - Fold {fold}")
    plt.xlabel("Epoche")
    plt.plotsize(60, 16)
    return plt.build()


def make_leaderboard_table(outdir):
    """Generiert eine Rich-Tabelle des aktuellen Leaderboards."""
    table = Table(expand=True)
    table.add_column("Config ID", justify="center", style="cyan")
    table.add_column("LR", justify="right")
    table.add_column("Dropout", justify="right")
    table.add_column("Batch", justify="right")
    table.add_column("WD", justify="right")
    table.add_column("Acc (Mean)", justify="right", style="green", bold=True)
    table.add_column("AUC (Mean)", justify="right", style="magenta")
    table.add_column("Seeds", justify="center")

    rows = []
    for f in outdir.glob('trial_*.csv'):
        try:
            rows.append(pd.read_csv(f))
        except Exception:
            pass
            
    if not rows:
        table.add_row("-", "-", "-", "-", "-", "-", "-", "-")
        return table

    df = pd.concat(rows)
    agg = (df.groupby("cfg_id", as_index=False)
           .agg(
               lr=("lr", "first"),
               dropout=("dropout", "first"),
               batch_size=("batch_size", "first"),
               weight_decay=("weight_decay", "first"),
               acc_mean=("accuracy", "mean"),
               auc_mean=("roc_auc", "mean"),
               n_seeds=("seed", "nunique")
           )
           .sort_values("acc_mean", ascending=False)
           .head(8))

    for r in agg.itertuples():
        table.add_row(
            str(r.cfg_id),
            f"{r.lr:.5f}",
            f"{r.dropout:.2f}",
            str(int(r.batch_size)),
            f"{r.weight_decay:.5f}",
            f"{r.acc_mean:.4f}",
            f"{r.auc_mean:.4f}",
            str(r.n_seeds)
        )
    return table


class TuiEventLogger:
    """Event-Handler, der die Rich Live-Oberfläche im Terminal aktualisiert."""
    def __init__(self, trial_name, config_dict, outdir, live_layout, max_epochs, n_configs_total, current_config_idx):
        self.trial_name = trial_name
        self.config_dict = config_dict
        self.outdir = outdir
        self.layout = live_layout
        self.max_epochs = max_epochs
        
        self.n_configs_total = n_configs_total
        self.current_config_idx = current_config_idx
        
        self.current_fold = "N/A"
        self.current_fold_idx = 0
        self.n_folds = 5
        self.current_epoch = 0
        
        self.curves = {}
        self.status_msg = "Initialisiere..."
        
        # Setup Progress-Bars
        self.fold_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn()
        )
        self.epoch_progress = Progress(
            TextColumn("[bold green]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn()
        )
        
        self.fold_task = self.fold_progress.add_task("Folds abgeschlossen", total=self.n_folds)
        self.epoch_task = self.epoch_progress.add_task("Epochen-Fortschritt", total=self.max_epochs)
        
        self.update_layout()

    def __call__(self, ev):
        t = ev.get('type')
        if t == EV.RUN_START:
            self.n_folds = ev['n_folds']
            self.fold_progress.update(self.fold_task, total=self.n_folds, completed=0)
            self.status_msg = f"Starte {self.trial_name}"
            self.curves.clear()
        elif t == EV.FOLD_START:
            self.current_fold = ev['person']
            self.current_fold_idx = ev['idx']
            self.fold_progress.update(self.fold_task, completed=self.current_fold_idx)
            self.fold_progress.update(self.fold_task, description=f"Fold {self.current_fold_idx+1}/{self.n_folds} ({self.current_fold})")
            self.epoch_progress.update(self.epoch_task, completed=0, description=f"Epoche 0/{self.max_epochs}")
            self.curves[self.current_fold] = []
        elif t == EV.EPOCH:
            self.current_epoch = ev['epoch']
            self.epoch_progress.update(self.epoch_task, completed=self.current_epoch + 1)
            self.epoch_progress.update(self.epoch_task, description=f"Epoche {self.current_epoch+1}/{self.max_epochs}")
            self.curves[self.current_fold].append((ev['epoch'], ev['loss'], ev['val_loss'], ev['val_auc']))
            self.status_msg = f"Training: Loss={ev['loss']:.4f} | Val AUC={ev['val_auc']:.4f}"
            self.update_layout()
        elif t == EV.FOLD_END:
            self.fold_progress.update(self.fold_task, completed=self.current_fold_idx + 1)
            self.update_layout()
        elif t == EV.RUN_END:
            self.status_msg = f"Trial fertig! Acc: {ev['mean_acc']:.4f}"
            self.update_layout()

    def update_layout(self):
        # 1. Status-Panel befüllen
        status_table = Table.grid(padding=1)
        status_table.add_row("[bold cyan]Modell:[/bold cyan]", self.config_dict['model'])
        status_table.add_row("[bold cyan]Trial Name:[/bold cyan]", self.trial_name)
        status_table.add_row("[bold cyan]Progress:[/bold cyan]", f"Config {self.current_config_idx}/{self.n_configs_total}")
        status_table.add_row("[bold cyan]Hyperparameter:[/bold cyan]", 
                             f"LR={self.config_dict['lr']:.5f} | Drop={self.config_dict['dropout']:.2f} | "
                             f"Batch={self.config_dict['batch_size']} | WD={self.config_dict['weight_decay']:.5f}")
        status_table.add_row("[bold cyan]Meldung:[/bold cyan]", self.status_msg)
        
        progress_table = Table.grid(padding=0)
        progress_table.add_row(self.fold_progress)
        progress_table.add_row(self.epoch_progress)
        
        status_layout = Layout()
        status_layout.split_column(
            Layout(Panel(status_table, title="[bold white]Aktueller Lauf[/bold white]"), ratio=3),
            Layout(Panel(progress_table, title="[bold white]Fortschritt[/bold white]"), ratio=2)
        )
        
        self.layout["left"]["status"].update(status_layout)
        
        # 2. Leaderboard-Panel befüllen
        self.layout["left"]["leaderboard"].update(
            Panel(make_leaderboard_table(self.outdir), title="[bold white]Leaderboard (Seed-Mittel-Acc)[/bold white]")
        )
        
        # 3. Plot-Panel befüllen
        plot_string = get_plotext_string(self.curves, self.current_fold, self.max_epochs)
        self.layout["right"].update(
            Panel(Text.from_ansi(plot_string), title=f"[bold white]Lernkurve - Fold: {self.current_fold}[/bold white]")
        )


def sync_up(outdir):
    subprocess.run([
        'rclone', 'copy', str(outdir),
        f'r2:ml4scs-sweep/hp_grid/{outdir.parent.name}/{outdir.name}',
        '--s3-no-check-bucket'
    ], capture_output=True)


def select_config():
    """Zeigt eine interaktive Liste aller Configs im hp/ Ordner zur Auswahl."""
    hp_dir = ROOT / "configs" / "hp"
    configs = sorted(list(hp_dir.glob("*.json")))
    
    console.clear()
    console.print(Panel(
        "[bold green]ML4SCS - Deep Model Grid Search TUI Runner[/bold green]\n"
        "[dim]Wähle eine Hyperparameter-Config aus, um das Training im Terminal zu starten[/dim]",
        expand=False
    ))
    
    console.print("\n[bold yellow]Verfügbare Konfigurationen:[/bold yellow]")
    for idx, cfg in enumerate(configs):
        try:
            with open(cfg) as f:
                data = json.load(f)
            model = data.get("model", "Unbekannt")
            pool = data.get("pool", "Unbekannt")
            seeds = len(data.get("seeds", []))
            console.print(f"  [bold cyan][{idx + 1:02d}][/bold cyan] [bold white]{cfg.name:<25}[/bold white] (Model: {model:<12} | Pool: {pool:<7} | Seeds: {seeds})")
        except Exception:
            console.print(f"  [bold red][{idx + 1:02d}] {cfg.name} (Fehler beim Lesen)[/bold red]")
            
    console.print(f"  [bold cyan][q][/bold cyan]  [bold red]Beenden[/bold red]")
    
    while True:
        choice = console.input("\nWähle eine Config (Nummer eingeben): ").strip()
        if choice.lower() == 'q':
            sys.exit(0)
        try:
            val = int(choice)
            if 1 <= val <= len(configs):
                return configs[val - 1]
        except ValueError:
            pass
        console.print("[bold red]Ungültige Auswahl. Bitte Nummer eingeben.[/bold red]")


def main():
    config_path = select_config()
    
    # 1. Config laden & initialisieren
    raw = json.loads(config_path.read_text())
    spec = load_grid_spec(config_path)
    cfgs = grid_configs(spec.grid.model_dump())
    outdir = grid_outdir(spec, config_path)
    outdir.mkdir(parents=True, exist_ok=True)
    _check_or_write_meta(outdir, raw, len(cfgs))

    # W&B check
    wandb_enabled = os.environ.get("WANDB_API_KEY") is not None
    if wandb_enabled:
        # wandb initialisieren
        try:
            wandb.login()
        except Exception:
            wandb_enabled = False

    # 2. Fold-Namen laden
    from src.training.deep.train_loso import _select_sessions, _pool_plan, _load_all_sessions, _fold_splits
    fs = {"legacy": 50, "modern": 100}[spec.pool]
    profile = {"legacy": "50hz", "modern": "100hz_grav"}[spec.pool]
    sessions = _select_sessions(include_all=False, min_windows=0, profile=profile)
    plan = _pool_plan(sessions, spec.pool)
    data = _load_all_sessions(sessions, spec.win * fs, fs // 2, plan, max_gap_ms=2500.0)
    persons = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    person_ids = sorted(persons)
    splits = _fold_splits(person_ids, spec.folds)
    fold_names = ["+".join(sorted(test_group)) for test_group, _, _ in splits]

    # 3. Layout aufbauen
    layout = Layout()
    layout.split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1)
    )
    layout["left"].split_column(
        Layout(name="status", ratio=2),
        Layout(name="leaderboard", ratio=3)
    )

    # 4. Grid-Schleife starten
    n_configs = len(cfgs) * len(spec.seeds)
    current_idx = 0
    
    with Live(layout, refresh_per_second=4, screen=True) as live:
        for idx, cfg in enumerate(cfgs):
            for seed in spec.seeds:
                name = trial_name(spec.model, idx, seed)
                trial_csv = outdir / f"trial_{name}.csv"
                current_idx += 1
                
                if trial_csv.exists():
                    continue
                
                cfg_id = f"g{idx:02d}"
                sink = epoch_history_sink(
                    outdir / f"history_{name}.csv",
                    model=spec.model, cfg_id=cfg_id, seed=seed, lr=cfg["lr"],
                )
                
                # Lokaler TUI-Logger
                tui_logger = TuiEventLogger(
                    trial_name=name,
                    config_dict=cfg,
                    outdir=outdir,
                    live_layout=layout,
                    max_epochs=spec.max_epochs,
                    n_configs_total=n_configs,
                    current_config_idx=current_idx
                )
                
                # Optionaler W&B Logger dazuschalten
                if wandb_enabled:
                    from scripts.ml.run_grid_wandb import WandbEventLogger
                    wandb_config = {
                        "model": spec.model, "cfg_id": cfg_id, "seed": seed, **cfg,
                        "win": spec.win, "pool": spec.pool, "max_epochs": spec.max_epochs
                    }
                    w_logger = WandbEventLogger(
                        trial_name=name,
                        group=config_path.stem,
                        config=wandb_config,
                        fold_names=fold_names
                    )
                    events = tee(sink, tui_logger, w_logger)
                else:
                    events = tee(sink, tui_logger)
                
                try:
                    df = train_deep_loso(
                        spec.model, spec.win, pool=spec.pool, seed=seed,
                        lr=cfg["lr"], dropout=cfg["dropout"],
                        batch_size=cfg["batch_size"], weight_decay=cfg["weight_decay"],
                        patience=spec.patience, max_epochs=spec.max_epochs,
                        folds=spec.folds, on_event=events,
                    )
                    pd.DataFrame([{
                        "model": spec.model, "cfg_id": cfg_id, **cfg, "seed": seed,
                        "accuracy": float(df["accuracy"].mean()),
                        "roc_auc": float(df["roc_auc"].mean()),
                        "best_epoch": float(df["best_epoch"].mean()),
                    }]).to_csv(trial_csv, index=False)
                finally:
                    sink.close()
                
                sync_up(outdir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.clear()
        console.print("[bold red]Training durch Benutzer abgebrochen.[/bold red]")
        sys.exit(0)
