import os
import sys
import argparse
from pathlib import Path
import json
import pandas as pd
import subprocess

# Projekt-Root zum Python-Path hinzufügen (Datei liegt in scripts/ml/ → parents[2])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import wandb
except ImportError:
    print("Fehler: 'wandb' ist nicht installiert. Bitte installiere es mit: pip install wandb")
    sys.exit(1)

from src.training.deep.grid import load_grid_spec, grid_outdir, trial_name, _check_or_write_meta
from src.training.deep.hp_search import grid_configs
from src.training.deep.train_loso import train_deep_loso
from src.training.deep.history import epoch_history_sink, tee
from src.training import events as EV


def sync_up(outdir):
    print(f"--> Syncing {outdir.name} to Cloudflare R2...")
    subprocess.run([
        'rclone', 'copy', str(outdir),
        f'r2:ml4scs-sweep/hp_grid/{outdir.parent.name}/{outdir.name}',
        '--s3-no-check-bucket'
    ], check=True)


class WandbEventLogger:
    """Event-Handler, der Trainings-Metriken in Echtzeit an Weights & Biases (W&B) streamt."""
    def __init__(self, trial_name, group, config, fold_names):
        self.trial_name = trial_name
        self.group = group
        self.config = config
        self.fold_names = fold_names
        self.run = None

    def __call__(self, ev):
        t = ev.get('type')
        if t == EV.RUN_START:
            # Starte einen neuen W&B Run für diese spezifische Config + Seed
            self.run = wandb.init(
                project="ML4SCS_HP_Grid",
                group=self.group,
                name=self.trial_name,
                config=self.config,
                reinit=True
            )
        elif t == EV.EPOCH:
            fold_idx = ev['fold']
            fold_name = (
                self.fold_names[fold_idx]
                if fold_idx < len(self.fold_names)
                else f"fold_{fold_idx}"
            )
            epoch = ev['epoch']
            # Logge Metriken für diesen spezifischen Fold
            wandb.log({
                f"{fold_name}/loss": ev['loss'],
                f"{fold_name}/val_loss": ev['val_loss'],
                f"{fold_name}/val_auc": ev['val_auc'],
                f"{fold_name}/val_acc": ev['val_acc'],
            }, step=epoch)
        elif t == EV.FOLD_END:
            fold_name = ev['person']
            # Logge die finalen Metriken des Folds im Run-Summary
            if self.run:
                self.run.summary[f"{fold_name}/final_acc"] = ev['acc']
                self.run.summary[f"{fold_name}/final_auc"] = ev['auc']
                self.run.summary[f"{fold_name}/final_f1"] = ev['f1']
        elif t == EV.RUN_END:
            if self.run:
                # Logge aggregierte CV-Ergebnisse
                self.run.summary["cv_mean_acc"] = ev['mean_acc']
                self.run.summary["cv_std_acc"] = ev['std_acc']
                self.run.summary["cv_mean_auc"] = ev['auc']
                self.run.summary["cv_mean_f1"] = ev['f1']
                for scale, acc in ev.get('burst', {}).items():
                    self.run.summary[f"cv_burst_acc_{scale}"] = acc
                self.run.finish()


def run_grid_wandb(config_path: Path):
    config_path = Path(config_path)
    raw = json.loads(config_path.read_text())
    spec = load_grid_spec(config_path)
    cfgs = grid_configs(spec.grid.model_dump())
    outdir = grid_outdir(spec, config_path)
    outdir.mkdir(parents=True, exist_ok=True)
    _check_or_write_meta(outdir, raw, len(cfgs))

    # Hole Fold-Namen, um Fold-Indizes hübsch zu mappen
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

    print(f"Starte Grid-Search für {config_path.stem} ({len(cfgs)} Configs x {len(spec.seeds)} Seeds)")

    for idx, cfg in enumerate(cfgs):
        for seed in spec.seeds:
            name = trial_name(spec.model, idx, seed)
            trial_csv = outdir / f"trial_{name}.csv"
            
            # Resume-Check
            if trial_csv.exists():
                print(f"Skippe fertigen Trial: {name}")
                continue
            
            cfg_id = f"g{idx:02d}"
            sink = epoch_history_sink(
                outdir / f"history_{name}.csv",
                model=spec.model, cfg_id=cfg_id, seed=seed, lr=cfg["lr"],
            )
            
            wandb_config = {
                "model": spec.model,
                "cfg_id": cfg_id,
                "seed": seed,
                "lr": cfg["lr"],
                "dropout": cfg["dropout"],
                "batch_size": cfg["batch_size"],
                "weight_decay": cfg["weight_decay"],
                "win": spec.win,
                "pool": spec.pool,
                "max_epochs": spec.max_epochs,
            }
            
            w_logger = WandbEventLogger(
                trial_name=name,
                group=config_path.stem,  # Gruppiert nach Config-Name (z.B. tcn6)
                config=wandb_config,
                fold_names=fold_names
            )
            
            # Verbinde den Standard-History-Sink mit dem W&B-Logger
            events = tee(sink, w_logger)
            
            try:
                print(f"\n>>> Starte Trial: {name} (Config {idx+1}/{len(cfgs)}, Seed {seed})")
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
    parser = argparse.ArgumentParser(description="Grid Search training runner with Weights & Biases logging.")
    parser.add_argument("config", type=str, help="Pfad zur Config-Datei, z. B. configs/hp/smoke_tcn.json")
    args = parser.parse_args()
    
    if not os.environ.get("WANDB_API_KEY"):
        print("Hinweis: WANDB_API_KEY Env-Variable ist nicht gesetzt. Falls nötig, logge dich mit 'wandb login' ein.")
        
    run_grid_wandb(args.config)
