# Documentation — ML4SCS Experiment History & Deep-Dives

`CLAUDE.md` (repo root) is the **lean operational reference**: current state,
how to run the pipeline, architecture map, data schemas, and the gotchas that
still bite. This folder holds the **full experimental history** that CLAUDE.md
used to carry inline — preserved verbatim, searchable, but out of the way.

- **[headline_history.md](headline_history.md)** — the RF LOSO headline lineage
  (N=3 → 20 cohort evolution). CLAUDE.md keeps only the *current* headline and
  links here for the predecessors.
- **[experiment_log.md](experiment_log.md)** — negative results & falsifications,
  per-cohort gap-ablation narratives (N=7/8/10), and the detailed deep-model /
  fusion / transfer numbers that CLAUDE.md used to spell out per script.
- **[hp_grid_leaderboard.md](hp_grid_leaderboard.md)** — the deep-model HP-grid
  leaderboard (best config per architecture, grouped-5-fold search) pulled from
  wandb `ML4SCS_HP_Grid`, with the noise-floor / selection-bias caveats. Snapshot
  2026-07-06; the whole TCN/GRU-hybrid family clusters at 0.91–0.93 (no separation).
- **[fusion_and_run_plan.md](fusion_and_run_plan.md)** — which model pairings are
  still worth testing (ranked by residual-correlation logic, not solo strength),
  why further hybrid architectures are dropped, and the prioritized pod queue for
  the remaining runs (Stage-2 confirmation, N=22 refresh, fusion tests).
  Snapshot 2026-07-07.

The per-experiment `reports/*.md` files remain the **primary** detailed source;
this folder is the consolidated narrative + the lineage that no single report
holds. Durable project facts / feedback / findings live in the Claude memory
system.
