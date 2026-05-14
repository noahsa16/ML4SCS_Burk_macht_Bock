# Dashboard Polish Phase 1 — Structural Audit

**Date:** 2026-05-11
**Base commit:** 417c6c2
**Scope:** 7 CSS files in `static/css/` + 5 view partials in `static/views/`.

This is a code-pattern audit, not a visual review. Every finding here
has an objective fix (a token to use, a missing rule to add). Noah can
mark rows to skip with "× skip" in the Status column.

---

## 1. Type-scale wildgrowth

Distinct font-size values present in the codebase today:

| Value | Files | Status | Proposed token |
|---|---|---|---|
| 10px | base.css, session-detail.css (×4), connections.css (×2), recording.css (×3), sessions.css, system.css (×2) | | `--text-xs` 11px |
| 10.5px | connections.css, recording.css (×2), topbar.css | | `--text-xs` 11px |
| 11px | base.css (×2), session-detail.css, connections.css, recording.css (×3), sessions.css, system.css | | `--text-xs` 11px |
| 11.5px | base.css (×3), session-detail.css, connections.css, recording.css, topbar.css (×2) | | `--text-xs` 11px |
| 12px | base.css, session-detail.css (×5), connections.css, recording.css, sessions.css (×4), system.css | | `--text-sm` 12px |
| 12.5px | sessions.css (×3), topbar.css | | `--text-sm` 12px |
| 13px | base.css (×3), session-detail.css (×4), connections.css, recording.css (×4), sessions.css (×3), topbar.css | | `--text-base` 14px |
| 13.5px | sessions.css | | `--text-base` 14px |
| 14px | base.css, session-detail.css, connections.css, recording.css | | `--text-base` 14px |
| 15px | session-detail.css (×2), recording.css, topbar.css, sessions.css | | `--text-base` 14px or `--text-md` 18px (context-dependent) |
| 18px | session-detail.css, connections.css | | `--text-md` 18px |
| 19px | topbar.css | | `--text-md` 18px |
| 20px | recording.css | | `--text-md` 18px |
| 22px | session-detail.css (×3), sessions.css | | `--text-lg` 22px |
| 28px | recording.css | | `--text-lg` 22px or `--text-xl` 32px |
| 32px | recording.css | | `--text-xl` 32px |
| 38px | sessions.css | | `--text-xl` 32px |

**Target scale (6 sizes):** `--text-xs` 11px, `--text-sm` 12px,
`--text-base` 14px, `--text-md` 18px, `--text-lg` 22px, `--text-xl` 32px.

The collapse from 17 → 6 follows a roughly modular scale (≈1.25 ratio
between adjacent steps from base upward, slightly compressed below).
Noah can override any merge by writing the target value in the Status
column.

---

## 2. Spacing-rhythm breaks

Distinct padding/margin/gap values not on a 4/8/12/16/24/32/48/64 scale.

| File | Line | Property | Value | Proposed |
|---|---|---|---|---|
| connections.css:2 | 2 | padding | 10px 16px | `--space-2` 8px / `--space-4` 16px → `8px 16px` |
| connections.css:2 | 2 | gap | 20px | `--space-5` 24px |
| connections.css:3 | 3 | gap | 2px | keep (micro gap, not spatial rhythm) |
| connections.css:12 | 12 | gap | 5px | `--space-1` 4px |
| connections.css:13 | 13 | gap | 8px | `--space-2` 8px ✓ |
| connections.css:13 | 13 | padding | 6px 10px | `--space-2` 8px / `--space-3` 12px → `8px 12px` |
| connections.css:14 | 14 | padding | 2px 6px | `--space-1` 4px / `--space-1` 4px → `2px 4px` (or keep for badge) |
| connections.css:22 | 22 | gap | 10px | `--space-2` 8px or `--space-3` 12px |
| connections.css:25 | 25 | padding | 13px | `--space-3` 12px |
| connections.css:40 | 40 | gap | 6px | `--space-1` 4px or `--space-2` 8px |
| connections.css:55 | 55 | margin-top | 14px | `--space-4` 16px |
| connections.css:56 | 56 | padding | 10px 12px | `--space-3` 12px (both axes) → `12px` |
| base.css:85 | 85 | padding | 28px 32px | `--space-7` 48px / `--space-6` 32px → `32px` (all axes) or keep 28/32 as `24px 32px` |
| base.css:91 | 91 | padding | 18px 20px | `--space-5` 24px / `--space-5` 24px → `24px` |
| base.css:100 | 100 | padding | 26px 28px | `--space-6` 32px both → `32px` |
| base.css:131 | 131 | padding | 14px 16px | `--space-4` 16px (both) → `16px` |
| base.css:142 | 142 | padding | 3px 0 | `--space-1` 4px → `4px 0` |
| base.css:167 | 167 | margin-top | 10px | `--space-2` 8px or `--space-3` 12px |
| base.css:185 | 185 | margin-bottom | 18px | `--space-5` 24px or `--space-4` 16px |
| base.css:221 | 221 | padding | 5px 11px | `--space-1` 4px / `--space-3` 12px → `4px 12px` |
| base.css:238 | 238 | padding | 10px 18px | `--space-2` 8px / `--space-5` 24px → `8px 16px` |
| session-detail.css:9 | 9 | gap | 18px | `--space-4` 16px or `--space-5` 24px |
| session-detail.css:9 | 9 | margin | 12px 0 16px | `--space-3` / 0 / `--space-4` → `12px 0 16px` ✓ (already 12/16) |
| session-detail.css:23 | 23 | padding | 10px 12px | `--space-3` 12px both → `12px` |
| session-detail.css:28 | 28 | padding | 4px 7px | `--space-1` 4px / `--space-2` 8px → `4px 8px` |
| session-detail.css:33 | 33 | padding | 3px 9px | `--space-1` 4px / `--space-2` 8px → `4px 8px` |
| session-detail.css:37 | 37 | margin | 6px 0 14px | `--space-2` 8px → `8px 0 16px` |
| session-detail.css:40 | 40 | gap | 14px | `--space-4` 16px |
| session-detail.css:42 | 42 | padding | 12px 14px | `--space-3` 12px both → `12px` |
| session-detail.css:72 | 72 | padding | 14px 28px | `--space-4` 16px / `--space-6` 32px → `16px 32px` |
| session-detail.css:83 | 83 | gap | 14px | `--space-4` 16px |
| session-detail.css:84 | 84 | padding | 18px 22px | `--space-5` 24px both → `24px` |
| session-detail.css:84 | 84 | margin-bottom | 18px | `--space-5` 24px or `--space-4` 16px |
| session-detail.css:92 | 92 | gap | 12px | `--space-3` 12px ✓ |
| session-detail.css:97 | 97 | padding | 4px 10px | `--space-1` 4px / `--space-2` 8px → `4px 8px` |
| session-detail.css:111 | 111 | padding | 14px 20px | `--space-4` 16px / `--space-5` 24px → `16px 24px` |
| session-detail.css:112 | 112 | gap | 10px | `--space-2` 8px or `--space-3` 12px |
| session-detail.css:122 | 122 | padding | 2px 7px | keep (badge micro-padding) or `2px 8px` |
| session-detail.css:125 | 125 | padding | 4px 20px 18px | `--space-1` 4px / `--space-5` 24px → `4px 24px 16px` |
| sessions.css:3 | 3 | padding | 9px 12px | `--space-2` 8px / `--space-3` 12px → `8px 12px` |
| sessions.css:14 | 14 | padding | 10px 12px | `--space-3` 12px both → `12px` |
| sessions.css:31 | 31 | padding | 40px | `--space-7` 48px or `--space-6` 32px |
| sessions.css:36 | 36 | padding | 56px 24px | `--space-7` 48px / `--space-5` 24px → `48px 24px` |
| sessions.css:57 | 57 | margin-top | 18px | `--space-4` 16px or `--space-5` 24px |
| sessions.css:84 | 84 | gap | 10px | `--space-2` 8px or `--space-3` 12px |
| sessions.css:85 | 85 | margin-bottom | 20px | `--space-5` 24px or `--space-4` 16px |
| sessions.css:91 | 91 | padding | 7px 11px | `--space-2` 8px / `--space-3` 12px → `8px 12px` |
| sessions.css:129 | 129 | margin-bottom | 18px | `--space-4` 16px or `--space-5` 24px |
| sessions.css:130 | 130 | margin-bottom | 22px | `--space-5` 24px |
| recording.css:2 | 2 | gap | 20px | `--space-5` 24px |
| recording.css:4 | 4 | gap | 14px | `--space-4` 16px |
| recording.css:10 | 10 | padding | 8px 11px | `--space-2` 8px / `--space-3` 12px → `8px 12px` |
| recording.css:19 | 19 | padding | 8px 11px | `--space-2` 8px / `--space-3` 12px → `8px 12px` |
| recording.css:24 | 24 | gap | 7px | `--space-2` 8px |
| recording.css:25 | 25 | padding | 9px 18px | `--space-2` 8px / `--space-5` 24px → `8px 16px` |
| recording.css:32 | 32 | padding | 11px | `--space-3` 12px |
| recording.css:43 | 43 | margin | 14px 0 4px | `--space-4` 16px / 0 / `--space-1` 4px → `16px 0 4px` |
| recording.css:47 | 47 | padding | 10px 12px | `--space-3` 12px both → `12px` |
| recording.css:55 | 55 | gap | 14px | `--space-4` 16px |
| recording.css:60 | 60 | padding | 14px 16px | `--space-4` 16px both → `16px` |
| recording.css:86 | 86 | padding | 10px 12px | `--space-3` 12px both → `12px` |
| recording.css:99 | 99 | padding | 3px 9px 3px 7px | `--space-1` 4px / `--space-2` 8px both axes → `4px 8px` |
| recording.css:113 | 113 | gap | 7px | `--space-2` 8px |
| recording.css:116 | 116 | gap | 18px | `--space-4` 16px or `--space-5` 24px |
| system.css:3 | 3 | gap | 14px | `--space-4` 16px |
| system.css:10 | 10 | padding | 7px 10px | `--space-2` 8px / `--space-2` 8px → `8px` |
| system.css:11 | 11 | padding | 6px 10px | `--space-1` 4px / `--space-2` 8px → `4px 8px` or `6px 12px` |
| topbar.css:7 | 7 | padding | 14px 32px | `--space-4` 16px / `--space-6` 32px → `16px 32px` |
| topbar.css:40 | 40 | padding | 8px 14px | `--space-2` 8px / `--space-4` 16px → `8px 16px` |
| topbar.css:69 | 69 | padding | 0 14px | 0 / `--space-4` 16px → `0 16px` |
| topbar.css:103 | 103 | padding | 5px 14px 5px 10px | `--space-1` 4px / `--space-4` 16px / `--space-1` 4px / `--space-2` 8px → `4px 16px 4px 8px` |

**Target scale (8 steps):** `--space-1` 4px, `--space-2` 8px,
`--space-3` 12px, `--space-4` 16px, `--space-5` 24px, `--space-6` 32px,
`--space-7` 48px, `--space-8` 64px.

---

## 3. Transition inconsistency

| File | Line | Declaration | Proposed |
|---|---|---|---|
| connections.css:31 | 31 | `transition: border-color 0.2s, color 0.2s` | `transition: border-color var(--dur-fast) var(--ease-default), color var(--dur-fast) var(--ease-default)` |
| base.css:106 | 106 | `transition: background 0.3s ease` | `transition: background var(--dur-slow) var(--ease-default)` |
| base.css:134 | 134 | `transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease` | `transition: transform var(--dur-fast) var(--ease-default), border-color var(--dur-fast) var(--ease-default), box-shadow var(--dur-fast) var(--ease-default)` |
| base.css:171 | 171 | `transition: color 0.15s ease` | `transition: color var(--dur-fast) var(--ease-default)` |
| base.css:176 | 176 | `transition: transform 0.2s ease` | `transition: transform var(--dur-fast) var(--ease-default)` |
| base.css:239 | 239 | `transition: transform 0.3s ease` | `transition: transform var(--dur-slow) var(--ease-default)` |
| recording.css:13 | 13 | `transition: border-color 0.15s` | `transition: border-color var(--dur-fast) var(--ease-default)` |
| recording.css:27 | 27 | `transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, transform 0.08s ease` | `transition: background var(--dur-fast) var(--ease-default), color var(--dur-fast) var(--ease-default), border-color var(--dur-fast) var(--ease-default), transform var(--dur-fast) var(--ease-default)` |
| recording.css:80 | 80 | `transition: opacity 0.3s ease` | `transition: opacity var(--dur-slow) var(--ease-default)` |
| recording.css:177 | 177 | `transition: opacity 0.3s ease` | `transition: opacity var(--dur-slow) var(--ease-default)` |
| session-detail.css:117 | 117 | `transition: transform 0.15s ease` | `transition: transform var(--dur-fast) var(--ease-default)` |
| sessions.css:6 | 6 | `transition: background 0.1s` | `transition: background var(--dur-fast) var(--ease-default)` |
| sessions.css:8 | 8 | `transition: background 0.12s ease, box-shadow 0.12s ease` | `transition: background var(--dur-fast) var(--ease-default), box-shadow var(--dur-fast) var(--ease-default)` |
| sessions.css:61 | 61 | `transition: color 0.15s ease, border-color 0.15s ease, transform 0.08s ease` | `transition: color var(--dur-fast) var(--ease-default), border-color var(--dur-fast) var(--ease-default), transform var(--dur-fast) var(--ease-default)` |
| sessions.css:74 | 74 | `transition: transform 0.12s ease, color 0.12s ease, border-color 0.12s ease, background 0.12s ease` | `transition: transform var(--dur-fast) var(--ease-default), color var(--dur-fast) var(--ease-default), border-color var(--dur-fast) var(--ease-default), background var(--dur-fast) var(--ease-default)` |
| sessions.css:94 | 94 | `transition: border-color 0.15s ease, box-shadow 0.15s ease` | `transition: border-color var(--dur-fast) var(--ease-default), box-shadow var(--dur-fast) var(--ease-default)` |
| topbar.css:22 | 22 | `transition: color 0.15s ease, transform 0.08s ease` | `transition: color var(--dur-fast) var(--ease-default), transform var(--dur-fast) var(--ease-default)` |
| topbar.css:45 | 45 | `transition: opacity 0.2s ease, transform 0.2s ease` | `transition: opacity var(--dur-fast) var(--ease-default), transform var(--dur-fast) var(--ease-default)` |
| topbar.css:74 | 74 | `transition: color 0.15s ease, transform 0.08s ease` | `transition: color var(--dur-fast) var(--ease-default), transform var(--dur-fast) var(--ease-default)` |
| topbar.css:109 | 109 | `transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease` | `transition: background var(--dur-fast) var(--ease-default), border-color var(--dur-fast) var(--ease-default), transform var(--dur-fast) var(--ease-default)` |
| topbar.css:120 | 120 | `transition: background 0.2s ease` | `transition: background var(--dur-fast) var(--ease-default)` |
| topbar.css:142 | 142 | `transition: background 0.15s ease, border-color 0.15s ease, transform 0.08s ease, color 0.15s ease` | `transition: background var(--dur-fast) var(--ease-default), border-color var(--dur-fast) var(--ease-default), transform var(--dur-fast) var(--ease-default), color var(--dur-fast) var(--ease-default)` |
| topbar.css:153 | 153 | `transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1)` | `transition: transform var(--dur-slow) var(--ease-default)` |

**Target tokens:** `--dur-fast` 140ms, `--dur-slow` 240ms,
`--ease-default` `cubic-bezier(0.2, 0.6, 0.2, 1)`.

Rationale for collapsing 6 durations → 2: most current durations (0.1,
0.12, 0.15) are "snap-to-state" feedback (hover, focus) — those go to
`--dur-fast`. The 0.2 and 0.3 values are skeleton-shimmer-adjacent
"settle" feel — those go to `--dur-slow`.

---

## 4. Border-radius drift

All non-token `border-radius` values found (exceptions: `50%` for circular indicators — geometric necessity):

| File | Line | Value | Proposed |
|---|---|---|---|
| base.css:123 | 123 | `border-radius: 50%` | keep (dot indicator, circular) |
| base.css:225 | 225 | `border-radius: 50%` | keep (pill dot, circular) |
| connections.css:29 | 29 | `border-radius: 50%` | keep (network node circle) |
| connections.css:49 | 49 | `border-radius: 50%` | keep (arrow head dot) |
| recording.css:56 | 56 | `border-radius: 2px` | `--radius-xs` |
| recording.css:104 | 104 | `border-radius: 50%` | keep (status dot, circular) |
| topbar.css:118 | 118 | `border-radius: 50%` | keep (status dot, circular) |

No non-50% hardcoded radius values found outside of the above. All other `border-radius` declarations already use `var(--radius-*)` tokens. Only `recording.css:56` (`.leg-dot`) uses a raw `2px` — it should map to `--radius-xs`.

---

## 5. Off-palette colors

| File | Line | Hardcoded color | Proposed |
|---|---|---|---|
| base.css:238 | 238 | `#fff` | `var(--text-on-dark)` (new token) or keep as `#fff` (always white-on-dark-sidebar) |
| recording.css:32 | 32 | `#fff` | same as above — `color: #fff` on primary button |
| recording.css:35 | 35 | `oklch(0.52 0.18 24)` | `var(--red-h)` (new token for red hover) |
| recording.css:39 | 39 | `#fff` | keep or `var(--text-on-dark)` |
| recording.css:40 | 40 | `oklch(0.52 0.135 148)` | `var(--green-h)` (new token for green hover) |
| recording.css:41 | 41 | `#fff` | keep or `var(--text-on-dark)` |
| recording.css:125 | 125 | `oklch(0.700 0.020 60 / 0.25)` | `var(--border)` with opacity, or new `--border-subtle` token |
| recording.css:147 | 147 | `oklch(0.560 0.155 70)` | `var(--yellow)` (existing token) |
| recording.css:148 | 148 | `oklch(0.520 0.180 24)` | `var(--red)` (existing token) |
| session-detail.css:35 | 35 | `#d2a300` | `var(--warn)` already present as fallback; remove fallback or add `--warn` token |
| session-detail.css:35 | 35 | `oklch(0.770 0.140 88 / 0.5)` | `var(--yellow)` with opacity — e.g. `oklch(from var(--yellow) l c h / 0.5)` or `color-mix(in oklch, var(--yellow) 50%, transparent)` |
| session-detail.css:36 | 36 | `#c54a4a` | `var(--err)` already present as fallback; remove fallback or add `--err` token |
| session-detail.css:36 | 36 | `oklch(0.620 0.190 25 / 0.5)` | `var(--red)` with opacity |
| session-detail.css:79 | 79 | `#b08000` | add `--warn` token = `oklch(0.720 0.135 88)` then use `var(--warn)` |
| session-detail.css:79 | 79 | `oklch(0.770 0.140 88 / 0.55)` | `color-mix(in oklch, var(--yellow) 55%, transparent)` |
| session-detail.css:79 | 79 | `oklch(0.770 0.140 88 / 0.10)` | `color-mix(in oklch, var(--yellow) 10%, transparent)` |
| session-detail.css:80 | 80 | `#c54a4a` | add `--err` token = `oklch(0.575 0.175 24)` then use `var(--err)` |
| session-detail.css:80 | 80 | `oklch(0.620 0.190 25 / 0.55)` | `color-mix(in oklch, var(--red) 55%, transparent)` |
| session-detail.css:80 | 80 | `oklch(0.620 0.190 25 / 0.08)` | `color-mix(in oklch, var(--red) 8%, transparent)` |
| session-detail.css:101 | 101 | `#b08000` | `var(--warn)` |
| session-detail.css:101 | 101 | `oklch(0.770 0.140 88 / 0.45)` | `color-mix(in oklch, var(--yellow) 45%, transparent)` |
| session-detail.css:102 | 102 | `#c54a4a` | `var(--err)` |
| session-detail.css:102 | 102 | `oklch(0.620 0.190 25 / 0.45)` | `color-mix(in oklch, var(--red) 45%, transparent)` |
| sessions.css:67 | 67 | `oklch(0.595 0.165 43 / 0.10)` | `color-mix(in oklch, var(--accent) 10%, transparent)` |
| sessions.css:113 | 113 | `oklch(0.595 0.165 43 / 0.25)` | `color-mix(in oklch, var(--accent) 25%, transparent)` |
| system.css:16 | 16 | `oklch(0.58 0.13 275 / 0.14)` | add `--purple` token, then `color-mix(...)` |
| system.css:16 | 16 | `oklch(0.55 0.14 275)` | `var(--purple)` |
| system.css:19 | 19 | `oklch(0.72 0.135 88 / 0.14)` | `color-mix(in oklch, var(--yellow) 14%, transparent)` |
| system.css:19 | 19 | `oklch(0.55 0.14 80)` | closest to `var(--yellow)` — darken; or add `--yellow-text` token |
| connections.css:17 | 17 | `oklch(0.55 0.15 275 / 0.15)` | add `--purple` token |
| connections.css:17 | 17 | `oklch(0.60 0.14 275)` | `var(--purple)` |
| connections.css:45 | 45 | `oklch(0.580 0.130 148 / 0.24)` | `color-mix(in oklch, var(--green) 24%, transparent)` |
| connections.css:46 | 46 | `oklch(0.720 0.135 88 / 0.22)` | `color-mix(in oklch, var(--yellow) 22%, transparent)` |
| base.css:139 | 139 | `oklch(0.300 0.025 55 / 0.20)` | `color-mix(in oklch, var(--sidebar) 20%, transparent)` |
| base.css:192 | 192 | `oklch(0.700 0.020 60 / 0.35)` | `var(--border)` with opacity — `color-mix(in oklch, var(--border) 60%, transparent)` |
| topbar.css:10 | 10 | `oklch(0.880 0.018 72 / 0.6)` | `color-mix(in oklch, var(--border) 60%, transparent)` |
| topbar.css:46 | 46 | `oklch(0.300 0.025 55 / 0.30)` | `color-mix(in oklch, var(--sidebar) 30%, transparent)` |
| session-detail.css:21 | 21 | `oklch(0.650 0.018 58 / 0.18)` | `color-mix(in oklch, var(--text3) 18%, transparent)` |

Common exceptions kept: `transparent`, `currentColor` (not listed above).

---

## 6. Hover / Focus-visible coverage

Interactive selectors and their hover/focus-visible state coverage:

| Selector | File | Has :hover | Has :focus-visible | Action |
|---|---|---|---|---|
| `.card-muted` | base.css | Yes (line 136) | No | Add `:focus-visible` ring |
| `.card-details-toggle` | base.css | Yes (line 173) | No | Add `:focus-visible` ring (button element) |
| `.btn` | recording.css | No (only variants have :hover) | No | Add `.btn:hover` and `.btn:focus-visible` base rules |
| `.btn-primary` | recording.css | Yes (line 33) | No | Add `:focus-visible` ring |
| `.btn-primary.stop` | recording.css | Yes (line 35) | No | Covered by parent `:focus-visible` if added |
| `.btn-outline` | recording.css | Yes (line 38) | No | Add `:focus-visible` ring |
| `.btn-green` | recording.css | Yes (line 40) | No | Add `:focus-visible` ring |
| `.btn-red` | recording.css | No | No | Add `:hover` (background: var(--red-h)) and `:focus-visible` |
| `.btn-sm` | recording.css | No | No | No standalone hover needed (applied via variant classes) |
| `input[type=text]` | recording.css | No | Yes (line 16, :focus) | Replace `:focus` with `:focus-visible` for keyboard-only ring |
| `select` | recording.css | No | Yes (line 18, via :focus) | Replace `:focus` with `:focus-visible` |
| `.tab` | topbar.css | Yes (line 76) | No | Add `:focus-visible` ring |
| `.brand` | topbar.css | Yes (line 25) | No | Add `:focus-visible` (it has a button role) |
| `.status-cluster` | topbar.css | Yes (line 111) | No | Add `:focus-visible` ring |
| `.theme-toggle` | topbar.css | Yes (line 144) | No | Add `:focus-visible` ring |
| `.click-row` | sessions.css | No | No | Add `:hover` background and `:focus-visible` outline |
| `.empty-state-action` | sessions.css | Yes (line 64) | No | Add `:focus-visible` ring |
| `.export-link` | sessions.css | Yes (line 76) | No | Add `:focus-visible` ring |
| `.filter-bar select` | sessions.css | No | Yes (line 97, :focus) | Add `:hover` and replace `:focus` with `:focus-visible` |
| `.filter-bar input[type="text"]` | sessions.css | No | Yes (line 96, :focus) | Add `:hover` and replace `:focus` with `:focus-visible` |
| `.filter-bar label.toggle` | sessions.css | No | No | Add `:hover` color shift and `:focus-visible` ring |
| `.filter-bar .reset-link` | sessions.css | Yes (line 124) | No | Add `:focus-visible` ring |
| `.session-detail-header .back-link` | session-detail.css | Yes (line 91) | No | Add `:focus-visible` ring |

A clickable element WITHOUT both states is a finding. No `:focus-visible` rules exist in any CSS file currently (all focus rules use `:focus`). This is a systemic gap — every interactive element needs `:focus-visible` added.

---

## Status legend
- ✓ apply — fix this in the migration pass
- × skip — leave as-is; Noah's call
- ⤸ defer — flag for Phase 2 or 3
- ✎ override — Noah wrote a different target value
