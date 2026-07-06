import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import sys
from pathlib import Path

ROOT = Path("/Users/noahsamel/PycharmProjects/ML4SCS_Burk_macht_Bock")
DATA_PROC = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"

def load_slice(sid, t_start, t_end):
    path = DATA_PROC / f"{sid}_merged.csv"
    if not path.exists():
        path = DATA_PROC / f"{sid}_merged_legacy.csv"
    df = pd.read_csv(path).sort_values("local_ts_ms").reset_index(drop=True)
    df["t_sec"] = (df["local_ts_ms"] - df["local_ts_ms"].iloc[0]) / 1000.0
    df["gyro_mag"] = np.linalg.norm(df[["rx", "ry", "rz"]].to_numpy(), axis=1)
    
    slice_df = df[(df["t_sec"] >= t_start) & (df["t_sec"] <= t_end)].copy()
    slice_df["t_rel"] = slice_df["t_sec"] - t_start
    return slice_df

def main():
    # 1. Load active windows
    # P17 Writing: S043 free_writing (active part)
    p17_write = load_slice("S043", 75.0, 85.0)
    # P17 Typing: S043 keyboard_typing (aggressive hunt-and-peck)
    p17_type = load_slice("S043", 200.0, 210.0)
    # P26 Typing: S055 keyboard_typing (control - quiet typing)
    p26_type = load_slice("S055", 500.0, 510.0)
    
    # 2. Calculate RMS
    rms_p17_write = np.sqrt((p17_write["gyro_mag"] ** 2).mean())
    rms_p17_type = np.sqrt((p17_type["gyro_mag"] ** 2).mean())
    rms_p26_type = np.sqrt((p26_type["gyro_mag"] ** 2).mean())
    
    print("--- Calculated Gyroscope RMS values (10-second windows) ---")
    print(f"P17 Writing (Active): RMS = {rms_p17_write:.4f} rad/s")
    print(f"P17 Typing (Aggressive): RMS = {rms_p17_type:.4f} rad/s")
    print(f"P26 Typing (Control): RMS = {rms_p26_type:.4f} rad/s")
    
    # 3. Plot side by side
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5), sharey=True)
    
    # Plot details
    configs = [
        (axes[0], p17_write, "tab:green", f"P17 Schreiben\n(Active Writing, RMS: {rms_p17_write:.2f})"),
        (axes[1], p17_type, "tab:red", f"P17 Tippen (FP)\n(Hunt-and-Peck, RMS: {rms_p17_type:.2f})"),
        (axes[2], p26_type, "tab:blue", f"P26 Tippen (Kontrolle)\n(Normal Typing, RMS: {rms_p26_type:.2f})")
    ]
    
    # Style plots
    for ax, df, color, title in configs:
        ax.plot(df["t_rel"], df["gyro_mag"], color=color, lw=0.8, alpha=0.9)
        ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
        ax.set_xlabel("Zeit  [s]", fontsize=10)
        ax.set_xlim(0, 10)
        ax.grid(True, linestyle="--", alpha=0.5)
        # Fill under the curve slightly for premium aesthetics
        ax.fill_between(df["t_rel"], df["gyro_mag"], color=color, alpha=0.1)
        
    axes[0].set_ylabel("‖gyro‖  [rad/s]", fontsize=11, fontweight="bold")
    
    # Y-axis limits
    ymax = max(p17_write["gyro_mag"].max(), p17_type["gyro_mag"].max(), p26_type["gyro_mag"].max()) * 1.05
    axes[0].set_ylim(0, ymax)
    
    plt.suptitle("Apple Watch Gyroskop-Magnitude  —  Schreiben vs. Tippen (10s Ausschnitte)", 
                 fontsize=14, fontweight="bold", y=1.02)
    
    plt.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FIG_DIR / "raw_compare_p17_p26.png"
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close()
    
    print(f"\nSuccessfully generated and saved plot to {out_path}")

if __name__ == "__main__":
    main()
