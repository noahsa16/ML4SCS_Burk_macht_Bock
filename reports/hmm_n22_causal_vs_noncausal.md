# RF + HMM auf N=22 (kausal vs nicht-kausal)

Legacy-Pool, 22 LOSO-Folds, HMM-Default (smoothing 1.0 / eps 1e-3 / gamma 1.0).

- HMM **kausal** (filter, Live-Gimmick):     acc 0.8855
- HMM **nicht-kausal** (smoother, Tagestracker): acc 0.9029
- Delta (nicht-kausal - kausal): +0.0175, p=0.0001 (SIGNIFIKANT), Folds besser: 19/22

