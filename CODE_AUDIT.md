# Scrybe iPhone + Apple Watch Code Audit

Generated 2026-08-28. Scope: 65 Swift files / 6,639 lines across the `WatchStreamer` iOS app, `WatchStreamer Watch App`, and `ScrybeTests`. The review covered the current working tree, including the uncommitted diagnostic-routing and UI changes. Python/server algorithm correctness, the trained model's statistical validity, and real-device behavior were not assumed from static code.

Findings cite exact source locations so each item can become an independent fix task. This audit is intentionally evidence-first; apart from this report, the audit phase made no further product-code changes.

---

## 1. Executive summary

Top items to address, in priority order:

1. **[Critical] The autonomous passive tracker is not implemented** — §5.1 — `watch_streamer/WatchStreamer Watch App/SensorProbe.swift:25-124`, `watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift:70-120`. The passive model and sensor recorder are used only by diagnostics/parity, not a production tracking pipeline.
2. **[High] Diagnostics can erase durable start/stop recovery state** — §5.2 — `watch_streamer/WatchStreamer/ServerCommandListener.swift:460-517`. Query commands still replace application context and cancel queued commands even though the Watch now discards those fallback copies.
3. **[High] A 12-hour probe can be restarted by duplicate transport delivery** — §5.3 — `watch_streamer/WatchStreamer/ServerCommandListener.swift:332-353`, `watch_streamer/WatchStreamer Watch App/MotionManager.swift:886-901`. `sensor_probe_start` lacks request identity and remains multi-transport.
4. **[High] Watch batches are acknowledged before durable acceptance** — §5.4 — `watch_streamer/WatchStreamer/PhoneBridge.swift:269-326`, `watch_streamer/WatchStreamer Watch App/MotionManager.swift:352-377`. A crash/suspension window can lose an already acknowledged batch.
5. **[High] The three central connectivity objects lack enforced isolation** — §3.1 — `MotionManager`, `PhoneBridge`, and `ServerCommandListener` publish UI state while crossing callback/GCD queues without actor boundaries.
6. **[High] The WebSocket epoch guard itself is raced** — §3.2 — `watch_streamer/WatchStreamer/ServerCommandListener.swift:30-39,104-137`. Reconnect and callback queues access the generation state without synchronization.
7. **[High/Security] Raw IMU and control traffic are unauthenticated plaintext** — §6.1 — `PhoneBridge.swift:41-54,402-481`, `ServerCommandListener.swift:73-86`. Release behavior can silently target a developer LAN endpoint.
8. **[High/Privacy] Retention and reset copy do not match stored data** — §6.2 — `PhoneBridge.swift:108-112,497-565`, `ProfileView.swift:202-237`. Raw IMU is backup-eligible and the reset action does not remove it.
9. **[High/UI] Core light-mode text colors fail contrast** — §8.1 — `ScrybeTheme.swift:16-25,52-56`. Measured contrast for `sepia` on the paper background is only 2.49–2.80:1.
10. **[Medium/Video] Focus loading is all-or-nothing** — §5.7 — `FocusStore.swift:41-58`. One auxiliary endpoint failure can make every product-video card stale/offline.

The connected live-tracking experience can be filmed after a real-device/server smoke test. The current code does **not** support an honest claim that the Watch autonomously records and classifies writing in the background.

## 2. Quick wins

- Update the two deprecated watchOS `onChange` calls — §4.1 — `WatchView_v2.swift:48,248`.
- Remove the unused `WTConnPill` — §9.5 — `WatchView_v2.swift:66-78`.
- Rename `WatchView_v2.swift` to `WatchView.swift`; it is active, not legacy — §9.4.
- Stop diagnostics from updating application context, cancelling durable transfers, or queueing impossible fallbacks — §5.2.
- Give `sensor_probe_start` an operation ID and single transport — §5.3.
- Change the diagnostic failure copy from “queued” to a truthful unreachable result — §5.2.
- Replace `theme.sepia` for body/caption text with a contrast-safe semantic token — §8.1.
- Replace the constant onboarding presentation binding with owned presentation state — §8.3.
- Give day-detail loading an error/retry state instead of swallowing the failure — §5.8.
- Make “Daten exportieren” produce a named file and accurately state its contents — §8.4.
- Add English translations for accessibility/status strings missing from the catalog — §8.6.
- Add a command-routing matrix test for direct, context, user-info, and poll paths — §5.11.

## 3. Concurrency

### 3.1 Observable connectivity owners have no enforced actor boundary
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:16-17,56-73,169-218`; `watch_streamer/WatchStreamer/ServerCommandListener.swift:8-39,104-137,269-295,409-457,526-574`; `watch_streamer/WatchStreamer Watch App/MotionManager.swift:8,110-130,773-997`
- **What:** Three central `ObservableObject` singletons publish UI/recording state while relying on comments and individual `DispatchQueue.main.async` calls rather than actor isolation.
- **Why:** A missed hop is a runtime data race today and becomes a broad Swift 6 migration failure; public methods remain callable from any executor.
- **Action:** Put UI/state facades on `@MainActor`, make delegate entry points immediately hop to their owner, and move disk/CPU/network work into actors or Sendable services returning typed values.
- **Severity:** High

### 3.2 WebSocket generation state is accessed across unsynchronized queues
- **Location:** `watch_streamer/WatchStreamer/ServerCommandListener.swift:30-39,104-137,526-537,577-594`
- **What:** `task`, `connectionEpoch`, and `sentHello` are reset during reconnect while receive/send callbacks read or mutate them directly on URLSession callback queues.
- **Why:** The epoch mechanism is designed to reject stale callbacks, but its own state can be stale/raced, permitting duplicate hello/listen/reconnect behavior.
- **Action:** Own the complete WebSocket state machine on one actor or serial executor and publish decoded state to the main actor.
- **Severity:** High

### 3.3 Poll/ack state is only partially locked
- **Location:** `watch_streamer/WatchStreamer/ServerCommandListener.swift:269-295,409-457,539-574`
- **What:** Locks protect the poll timestamp and session tuple, but poll handling still reads published connection/status properties and mutates `lastPollAckKey` from callback queues.
- **Why:** Partial locking can produce inconsistent status snapshots and duplicate acknowledgements under overlapping callbacks.
- **Action:** Replace per-field locks with one isolated poll/ack state machine that emits immutable status snapshots.
- **Severity:** High

### 3.4 Background diagnostics still pass through main-owned command state
- **Location:** `watch_streamer/WatchStreamer Watch App/MotionManager.swift:818-844,964-987`
- **What:** `sensor_probe_report` and `parity_check` run on a global queue but call `handleCommand`, which first applies configuration and reads recording/session/counter properties.
- **Why:** They can race start/stop/poll/UI work despite the nearby claim that diagnostics do not touch recording state.
- **Action:** Route direct diagnostics to a separate diagnostic service without entering the recording command dispatcher.
- **Severity:** High

### 3.5 Untyped dictionaries cross concurrency domains
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:189-211,269-326`; `watch_streamer/WatchStreamer/ServerCommandListener.swift:269-295,460-537`; `watch_streamer/WatchStreamer Watch App/MotionManager.swift:964-987`
- **What:** `[String: Any]` values and reply closures move among WCSession delegates, GCD queues, URLSession callbacks, and main.
- **Why:** `Any` is not Sendable; mutable Foundation values or future payload additions cannot be proven race-free.
- **Action:** Decode transport dictionaries immediately into immutable `Codable & Sendable` command, batch, status, and reply types.
- **Severity:** Medium

### 3.6 Callback networking obscures cancellation and ownership
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:402-481`; `watch_streamer/WatchStreamer/ServerCommandListener.swift:104-137,526-537`
- **What:** Upload and WebSocket lifecycles use nested completion handlers and GCD hops despite async APIs being available.
- **Why:** Cancellation, stale-task rejection, and executor ownership are manual and are already contributing to epoch/state complexity.
- **Action:** Migrate networking to structured tasks owned by dedicated actors with explicit cancellation handles.
- **Severity:** Medium

## 4. API modernity

### 4.1 Deprecated watchOS `onChange` overloads produce the only source warnings
- **Location:** `watch_streamer/WatchStreamer Watch App/WatchView_v2.swift:48,248-250`
- **What:** Both sites use `onChange(of:perform:)`, deprecated at the target's watchOS 10 minimum.
- **Why:** The fresh clean build emits two actionable warnings, obscuring future compiler signal.
- **Action:** Use the zero-argument or old/new-value watchOS 10 overload as appropriate.
- **Severity:** Low

### 4.2 Production targets remain in Swift 5 language mode
- **Location:** `watch_streamer/WatchStreamer.xcodeproj/project.pbxproj:501-505,535-539,566-570,598-602`
- **What:** iOS and Watch targets enable approachable/default actor isolation but still compile with `SWIFT_VERSION = 5.0`.
- **Why:** The current clean build cannot expose the strict-concurrency failures implied by §3; migration risk is deferred rather than removed.
- **Action:** Add a warning-only Swift 6/strict-concurrency CI configuration, fix isolation findings, then raise language mode deliberately.
- **Severity:** Medium

### 4.3 The test target minimum does not exercise the app's iOS 16 contract
- **Location:** `watch_streamer/WatchStreamer.xcodeproj/project.pbxproj:311-350,408,466`
- **What:** `ScrybeTests` targets iOS 26.4 while the application targets iOS 16.
- **Why:** Availability mistakes and fallback behavior for supported iOS 16–25 devices cannot be caught by that test configuration.
- **Action:** Align the unit-test deployment target with iOS 16 and add a separate newest-OS UI-test destination when needed.
- **Severity:** Medium

### 4.4 Repeated `DateFormatter` allocation should use modern/cached formatting
- **Location:** `watch_streamer/WatchStreamer/Scrybe/Logic/TimeFormatting.swift:21-60`; `watch_streamer/WatchStreamer/Scrybe/DayDetailView.swift:118-125`; `watch_streamer/WatchStreamer/Stores/EventLogStore.swift:15-17`
- **What:** Several display paths instantiate formatters repeatedly, including a formatter constructed for each weekday/date call.
- **Why:** It creates avoidable work during SwiftUI recomputation and fragments locale/time-zone behavior.
- **Action:** Centralize date semantics and use cached locale-keyed formatters or `FormatStyle` where the deployment target supports it.
- **Severity:** Low

## 5. Bugs / logic errors

### 5.1 The autonomous passive tracker has no production execution pipeline
- **Location:** `watch_streamer/WatchStreamer Watch App/SensorProbe.swift:25-124`; `watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift:13-55,70-120`
- **What:** `CMSensorRecorder` is read only by the manual sensor probe, and `WatchScrybeModel` is instantiated only by `WatchParityCheck`; no production code retrieves recorded samples, builds 250×3 windows, runs the passive model, persists decisions, or syncs writing time.
- **Why:** The product currently shown on iPhone is fed by connected FastAPI/live streaming, so filming or describing autonomous passive Watch tracking would claim a feature absent from the code.
- **Action:** Implement and validate a durable background retrieval → normalization/windowing → Core ML → aggregation → sync pipeline, or explicitly position tomorrow's video as a connected prototype.
- **Severity:** Critical

### 5.2 Direct diagnostics corrupt the durable command-transport contract
- **Location:** `watch_streamer/WatchStreamer/ServerCommandListener.swift:460-517`; `watch_streamer/WatchStreamer Watch App/MotionManager.swift:791-816,964-987`
- **What:** Every command cancels outstanding user-info, replaces application context, and may queue user-info, while the Watch now intentionally discards context/user-info copies of report/parity diagnostics.
- **Why:** A query can erase durable start/stop recovery state; its fallback is guaranteed not to run, and the caller is misleadingly told it was queued.
- **Action:** Classify transport semantics before sending: direct-reply diagnostics use only `sendMessage`; durable idempotent state uses context/user-info/poll recovery.
- **Severity:** High

### 5.3 `sensor_probe_start` remains duplicate/replay-prone
- **Location:** `watch_streamer/WatchStreamer/ServerCommandListener.swift:332-353,460-517`; `watch_streamer/WatchStreamer Watch App/MotionManager.swift:886-901`
- **What:** Probe start lacks an operation ID/dedup rule and is mirrored through live message, application context, and possible delayed user-info.
- **Why:** A duplicate or stale delivery can reset `startedAt`/requested duration and invalidate a scarce 12-hour hardware measurement.
- **Action:** Make probe start direct-only or idempotent with a stable operation ID and explicit already-started response.
- **Severity:** High

### 5.4 Watch batches are acknowledged before durable acceptance
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:269-326`; `watch_streamer/WatchStreamer Watch App/MotionManager.swift:352-377`
- **What:** The iPhone replies `ok=true` after validating and scheduling work, before main-queue insertion and debounced persistence; the Watch then considers the live delivery complete.
- **Why:** Suspension/crash/termination between reply and persistence can lose a batch that the Watch has already released.
- **Action:** Define acknowledgement as durable queue acceptance and return it only after an isolated queue/journal owns the batch.
- **Severity:** High

### 5.5 Delivery counters can double-count a timeout race
- **Location:** `watch_streamer/WatchStreamer Watch App/MotionManager.swift:352-375,461-470`
- **What:** The reply path calculates `stillInFlight` but discards it and always increments delivered count; a later successful fallback increments again.
- **Why:** Health/status can report delivery that did not win the terminal race or count the same batch twice.
- **Action:** Model live reply and background completion as mutually exclusive terminal outcomes and test both callback orders.
- **Severity:** Medium

### 5.6 Spill persistence hides disk failures and can report false safety
- **Location:** `watch_streamer/WatchStreamer Watch App/MotionManager.swift:497-525,658-706`
- **What:** Serialization/open/seek/write/compact/delete failures are mostly swallowed while counters are updated optimistically.
- **Why:** The UI can claim samples are safely spilled even when they never reached disk, undermining the data-loss guarantees.
- **Action:** Expose durable-spill health, handle every persistence result, and reconcile counts from the journal.
- **Severity:** Medium

### 5.7 Focus refresh is unnecessarily all-or-nothing
- **Location:** `watch_streamer/WatchStreamer/Stores/FocusStore.swift:41-58`
- **What:** Today, week, history, and time-of-day requests share one throwing `async let` tuple; one failure discards all successful results.
- **Why:** A nonessential endpoint can make every screen stale/offline during normal use or tomorrow's filming.
- **Action:** Commit each successful section independently and represent per-section freshness/errors.
- **Severity:** Medium

### 5.8 Day-detail failures are silently swallowed
- **Location:** `watch_streamer/WatchStreamer/Stores/FocusStore.swift:61-66`; `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift:51-68`
- **What:** `loadDay` ignores every error and leaves the history row indefinitely at “Laden …”.
- **Why:** Users receive no failure state or retry path when opening a day.
- **Action:** Publish idle/loading/loaded/error state per day and provide retry.
- **Severity:** Medium

### 5.9 Empty Today hides current live/offline status
- **Location:** `watch_streamer/WatchStreamer/Scrybe/TodayView.swift:21-25,32-80`
- **What:** Before any accumulated data, the screen shows only the empty ring/message; `LiveChip`, offline banner, and refreshable scroll content exist only in the nonempty branch.
- **Why:** A new user or product-video run cannot see whether detection is live, writing, disconnected, or stale precisely when setup feedback matters most.
- **Action:** Keep connection/live state visible in both empty and populated states and allow refresh in the empty state.
- **Severity:** Medium

### 5.10 Runtime parity does not validate provenance or channel identity
- **Location:** `watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift:73-112`; `watch_streamer/WatchStreamer/Scrybe/Logic/ScrybeModel.swift:24-57`; `watch_streamer/ScrybeTests/ScrybeModelParityTests.swift:24-64`
- **What:** Parity consumes shape/logits from the fixture but does not verify sidecar hashes, checkpoint identity, channel names/order, or sample rate at runtime; unit parity covers only the active iPhone model.
- **Why:** A stale model+fixture pair can remain internally green while being the wrong deployment artifact or channel contract.
- **Action:** Verify immutable manifest hashes and input schema at initialization and add passive provenance/parity coverage.
- **Severity:** Medium

### 5.11 Reliability state machines lack transport-order tests
- **Location:** `watch_streamer/ScrybeTests/` (current suite); routing logic at `ServerCommandListener.swift:460-517`, `MotionManager.swift:791-987`, `PhoneBridge.swift:269-326`
- **What:** Existing tests cover DTOs, evaluators, streaks, goals, and active model parity, but not command routing, ACK durability, duplicate callback order, or partial Focus failures.
- **Why:** The highest-risk failure modes depend on delivery ordering and cannot be protected by current pure-logic tests.
- **Action:** Add deterministic transport fakes and a route matrix covering live/context/user-info/poll, stale commands, timeout orderings, and durable acknowledgement.
- **Severity:** Medium

## 6. Security

### 6.1 Raw IMU and control traffic use unauthenticated plaintext transport
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:8-14,41-54,402-481`; `watch_streamer/WatchStreamer/ServerCommandListener.swift:73-86,104-136,526-536`; `watch_streamer/ATS.plist:6-10`; `watch_streamer/WatchAppInfo.plist:22-26`
- **What:** Motion samples, person/session identifiers, and control/status messages use HTTP/WS by default, with arbitrary ATS loads enabled and no request authentication.
- **Why:** Same-network observers can read activity data or inject/replay commands; a release can silently target a developer LAN.
- **Action:** Require HTTPS/WSS and authenticated requests for production, validate allowed hosts, narrow ATS exceptions to development, and remove the developer endpoint from release defaults.
- **Severity:** High

### 6.2 Raw IMU retention and reset behavior contradict the privacy surface
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:29-37,108-112,497-565`; `watch_streamer/WatchStreamer/Scrybe/ProfileView.swift:202-237`
- **What:** The raw upload queue is stored in Documents without visible backup/file-protection policy, while “local reset” removes only five preference keys and leaves queue/server/history state intact.
- **Why:** Sensitive motion data can enter device backups and users can reasonably believe a destructive reset removed more than it does.
- **Action:** Store the queue in protected Application Support, exclude it from backup, define retention, and offer an explicit delete-data flow whose copy precisely names local/server effects.
- **Severity:** High

### 6.3 Admin PIN is an obscurity gate, not access control
- **Location:** `watch_streamer/WatchStreamer/Stores/ScrybeSettings.swift:8-10,42-45`; `watch_streamer/WatchStreamer/Scrybe/ProfileView.swift:40-64`; `watch_streamer/WatchStreamer/Admin/AdminGateView.swift:42-55`
- **What:** The hidden entry uses five taps and defaults to PIN `0000`, stored in UserDefaults.
- **Why:** Anyone who discovers the gesture can access destructive repair controls; the source comment correctly says this is not a security feature.
- **Action:** Keep it explicitly operator-only in prototype builds; for distribution, use authenticated/biometric admin access or remove destructive controls from the consumer build.
- **Severity:** Medium

## 7. Performance

### 7.1 Date formatting allocates in frequently recomputed view paths
- **Location:** `watch_streamer/WatchStreamer/Scrybe/Logic/TimeFormatting.swift:31-60`; `watch_streamer/WatchStreamer/Scrybe/DayDetailView.swift:118-125`; `watch_streamer/WatchStreamer/Stores/EventLogStore.swift:15-17`
- **What:** Formatters are created for each display call or row property access.
- **Why:** History, trends, and day details can repeatedly allocate expensive Foundation formatters during body recomputation.
- **Action:** Use cached/locale-keyed formatting services or `FormatStyle` values.
- **Severity:** Low

### 7.2 Repeated transforms run directly from observable state during view evaluation
- **Location:** `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift:8-16`; `watch_streamer/WatchStreamer/Scrybe/TrendsView.swift:14-33`; `watch_streamer/WatchStreamer/Scrybe/DayDetailView.swift:10-29`
- **What:** Filtering, reversing, suffix arrays, reductions, and sample concatenation are recomputed whenever broad shared stores publish.
- **Why:** Current datasets are small, but 90-day history and intensity arrays make updates increasingly coupled to unnecessary UI work.
- **Action:** Derive immutable screen snapshots when network state changes and pass focused values to leaf views.
- **Severity:** Low

### 7.3 Broad singletons invalidate more UI than necessary
- **Location:** `watch_streamer/WatchStreamer/Stores/FocusStore.swift:4-20`; `watch_streamer/WatchStreamer/ServerCommandListener.swift:8-29`
- **What:** Many unrelated `@Published` properties share single observable objects consumed throughout Scrybe and Admin screens.
- **Why:** A poll/status tick can trigger recomputation in views that only need one field.
- **Action:** Split domain state or migrate to Observation with focused dependencies as part of the actor refactor.
- **Severity:** Low

## 8. SwiftUI / UI

### 8.1 Light-mode secondary text fails WCAG contrast
- **Location:** `watch_streamer/WatchStreamer/Scrybe/ScrybeTheme.swift:16-25,52-56`; examples at `TodayView.swift:49-53`, `TrendsView.swift:47-50,95-100`, `HistoryView.swift:54-77,101-107,123-126`, `ProfileView.swift:203-205`
- **What:** `sepia` (`#A8893F`) is widely used for caption/subheadline/body text over `paperTop`/`paperBottom`; calculated ratios are 2.80:1 and 2.49:1, below 4.5:1. `mutedInk` at 15% opacity is still fainter.
- **Why:** Secondary content becomes difficult to read and cannot support a Larger Text/contrast accessibility claim; it may also wash out in a recorded video.
- **Action:** Introduce separate decorative-gold and contrast-safe secondary-text tokens, then verify both paper extremes with Accessibility Inspector.
- **Severity:** High

### 8.2 Fixed 240-point Today ring is not adaptive
- **Location:** `watch_streamer/WatchStreamer/Scrybe/TodayView.swift:44-58,83-100`; `watch_streamer/WatchStreamer/Scrybe/Components/InkRing.swift:1-48`
- **What:** Empty and populated rings use a fixed 240×240 frame while center/subtitle text scales dynamically.
- **Why:** Accessibility text sizes, split view, landscape, and smaller phones can clip or compress surrounding content.
- **Action:** Use an adaptive container (`ViewThatFits` or geometry-capped size), scaled ring metrics, and large-text previews.
- **Severity:** Medium

### 8.3 Onboarding presentation uses an immutable synthetic binding
- **Location:** `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift:38-42`
- **What:** `fullScreenCover` receives `.constant(!onboardingDone)` rather than view-owned presentation state.
- **Why:** Presentation dismissal depends on modifier reconstruction instead of a writable binding and is brittle under lifecycle/restoration behavior.
- **Action:** Own explicit onboarding presentation state synchronized with the persisted completion flag.
- **Severity:** Medium

### 8.4 “Daten exportieren” is not a named data export
- **Location:** `watch_streamer/WatchStreamer/Scrybe/ProfileView.swift:202-229`
- **What:** `ShareLink` shares an in-memory JSON string containing only daily seconds, without a file, filename, MIME type, stretches, settings, or raw-data scope.
- **Why:** The action label and privacy paragraph imply a meaningful portable export, while receiving apps see plain text and incomplete content.
- **Action:** Export a documented, versioned JSON file via `Transferable`/file representation and make the UI state exactly which data is included.
- **Severity:** Medium

### 8.5 Hidden admin gesture is intentionally inaccessible
- **Location:** `watch_streamer/WatchStreamer/Scrybe/ProfileView.swift:40-64`
- **What:** The five-tap footer is implemented as an unlabelled gesture on text and deliberately concealed from VoiceOver.
- **Why:** Operators using VoiceOver, Voice Control, Switch Control, or keyboard cannot enter the admin panel.
- **Action:** Provide an accessibility-only named action or a separately discoverable operator route in admin/prototype builds without exposing it in the proband flow.
- **Severity:** Medium

### 8.6 English localization is incomplete for status and accessibility copy
- **Location:** `watch_streamer/WatchStreamer/Localizable.xcstrings` keys including `Schreibzeit heute`, `Tagesziel in Minuten`, `Zeitraum`, `Verlauf der letzten %lld Tage`, `Schreibintensität über die Session`, `PIN`, and several Admin strings; consuming sites include `InkRing.swift:44-47`, `RangeBarChart.swift:21-22`, `AdminGateView.swift:31-35`
- **What:** The catalog contains no English localization for multiple spoken/status strings while Profile offers an English language override.
- **Why:** Visible UI may switch language while VoiceOver and diagnostic surfaces remain German.
- **Action:** Complete the English catalog and add a localization completeness check for every user-facing/accessibility key.
- **Severity:** Medium

### 8.7 Custom charts expose summaries but insufficient values
- **Location:** `watch_streamer/WatchStreamer/Scrybe/Components/RangeBarChart.swift:11-23`; `watch_streamer/WatchStreamer/Scrybe/Components/IntensityCurve.swift:10-32`
- **What:** The 30-day chart announces only its title/count and the intensity curve only its title, without trend, range, peak, or representative values.
- **Why:** VoiceOver users cannot obtain the information encoded visually.
- **Action:** Provide concise derived accessibility values and, where useful, an adjustable/chart-descriptor representation.
- **Severity:** Medium

### 8.8 Reduced-motion handling is incomplete in delayed animations
- **Location:** `watch_streamer/WatchStreamer/Admin/AdminGateView.swift:48-55,102-106`; `watch_streamer/WatchStreamer/Scrybe/TodayView.swift:103-123`; `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift:53-58`
- **What:** Primary animation triggers are gated, but delayed callbacks are not cancellable and the custom shake geometry remains structurally present.
- **Why:** Rapid lifecycle/state changes can apply stale animation state, and reduced-motion verification remains dependent on branch timing.
- **Action:** Use cancellable tasks tied to view lifetime and ensure reduced-motion paths replace motion with a nonmoving state cue.
- **Severity:** Low

## 9. Dead code / duplication / refactor

### 9.1 `MotionManager` is a six-responsibility monolith
- **Location:** `watch_streamer/WatchStreamer Watch App/MotionManager.swift:8-140,158-323,325-490,493-738,747-997,1000-1119`
- **What:** The 1,120-line object owns capture, batching, connectivity, spill persistence, command protocol/configuration, and HealthKit workout lifecycle.
- **Why:** Unrelated state machines share mutable state and make passive-pipeline work likely to regress live delivery.
- **Action:** Extract typed sample/batch models, `SpillStore`, command router, capture service, and workout coordinator behind a thin UI facade.
- **Severity:** Medium

### 9.2 iPhone transport singletons are also oversized
- **Location:** `watch_streamer/WatchStreamer/ServerCommandListener.swift:8-608`; `watch_streamer/WatchStreamer/PhoneBridge.swift:16-565`
- **What:** WebSocket, WCSession, HTTP queue, persistence, dedup, diagnostics, status projection, and UI state are concentrated in two large objects.
- **Why:** Reliability behavior is hard to unit test and actor isolation requires manual mirrors/locks.
- **Action:** Split typed codecs, durable queue/uploader, command router, WebSocket client, diagnostics service, and main-actor presentation facades.
- **Severity:** Medium

### 9.3 Dictionary protocol and numeric coercion are duplicated
- **Location:** `watch_streamer/WatchStreamer/ServerCommandListener.swift:151-295,409-565`; `watch_streamer/WatchStreamer Watch App/MotionManager.swift:747-925`; `watch_streamer/WatchStreamer/PhoneBridge.swift:270-398`
- **What:** Command names, field keys, casing, and tolerant numeric conversion are independently repeated across targets.
- **Why:** Schema drift is already visible (`isRunning` versus `is_running`) and malformed fields silently default.
- **Action:** Introduce a shared typed protocol package/target and generate narrow property-list adapters for WatchConnectivity.
- **Severity:** Medium

### 9.4 `WatchView_v2.swift` is active but misleadingly versioned
- **Location:** `watch_streamer/WatchStreamer Watch App/WatchView_v2.swift:1-7,458-467`; `watch_streamer/WatchStreamer Watch App/WatchStreamerApp.swift:3-8`
- **What:** The filename suggests obsolete code, but it contains the only `WatchView` used by the Watch entry point.
- **Why:** A future cleanup can mistakenly delete active UI; repository navigation implies a nonexistent v1/v3 lineage.
- **Action:** Rename it to `WatchView.swift` through the synchronized Xcode group; do not delete it.
- **Severity:** Low

### 9.5 `WTConnPill` is genuine dead UI code
- **Location:** `watch_streamer/WatchStreamer Watch App/WatchView_v2.swift:66-78`
- **What:** The type has no reference outside its declaration.
- **Why:** It adds noise to an already oversized view file.
- **Action:** Delete it or intentionally integrate it into a connection surface.
- **Severity:** Low

### 9.6 Server-address normalization is duplicated
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:41-54`; `watch_streamer/WatchStreamer/ServerCommandListener.swift:73-86`
- **What:** HTTP and WebSocket URL trimming/scheme/default-port logic are separately implemented.
- **Why:** IPv6, TLS, explicit ports, or base paths can diverge between uploads and status/control.
- **Action:** Parse a single validated base URL with `URLComponents` and derive endpoints centrally.
- **Severity:** Low

### 9.7 Sparkline implementations have drifted
- **Location:** `watch_streamer/WatchStreamer/Admin/Sections/DataflowCard.swift:48-68`; `watch_streamer/WatchStreamer/Scrybe/Components/MiniSparkline.swift:5-33`; `watch_streamer/WatchStreamer Watch App/WatchView_v2.swift:175-195`
- **What:** Three components independently implement numeric polyline scaling and rendering.
- **Why:** Empty/single-value handling, accessibility, and visual normalization differ.
- **Action:** Consolidate iPhone implementations and keep a thin target-specific Watch wrapper if shared compilation is undesirable.
- **Severity:** Low

### 9.8 Settings keys and capture constants lack one source of truth
- **Location:** `watch_streamer/WatchStreamer/PhoneBridge.swift:42,177,217,225,240,245`; `watch_streamer/WatchStreamer/ServerCommandListener.swift:73,246-249`; `watch_streamer/WatchStreamer/Admin/Sections/SettingsCard.swift:4-6`; `watch_streamer/WatchStreamer Watch App/MotionManager.swift:29-35,747-756`
- **What:** UserDefaults keys, requested/effective settings, defaults, and limits are spread as literals across UI and both devices.
- **Why:** Configuration migrations have no compiler protection and can create displayed/runtime disagreement.
- **Action:** Define typed settings and a shared capture contract with documented requested/effective semantics.
- **Severity:** Low

No `TODO`, `FIXME`, `HACK`, `XXX`, debug `print`, `debugPrint`, or `NSLog` occurrences were found in the Swift scope. `ScrybeApp.swift` and `WatchStreamerApp.swift` are valid entry points for separate targets, not duplicates.

## 10. Cross-cutting recommendations

1. **Separate product state from transport mechanics.** Main-actor UI facades should consume immutable snapshots from WebSocket, WCSession, persistence, and inference actors. This resolves most §3 races and makes §5 reliability tests feasible.
2. **Make transport semantics part of the type system.** Commands should declare whether they are durable state, idempotent operations, or direct request/reply queries. A typed route prevents the contradictory behavior in §5.2–§5.4.
3. **Define one end-to-end passive contract before polishing further UI.** Specify sample source, window size/stride, channel order, time semantics, model hash, decision smoothing, persistence, retry, and server merge behavior; then implement and validate it on real hardware.
4. **Create a video/demo readiness mode without falsifying product behavior.** A connected-prototype video can use deterministic seeded server data and explicit connection health, but should not simulate autonomous Watch classification unless the production pipeline exists.
5. **Treat privacy copy as an executable contract.** Storage location, backup, encryption, retention, export, reset, server deletion, and network security must agree with the words shown in Profile.
6. **Use accessibility tokens, not decorative colors, for text.** Separate brand gold from semantic secondary text and test Dynamic Type, Increase Contrast, Reduce Motion, grayscale, and VoiceOver on every main screen.
7. **Add reliability tests before the 12-hour run.** A short deterministic transport matrix should prove duplicate, stale, timeout, crash-before-persist, reconnect, and late-callback behavior before spending twelve hours on hardware evidence.

## 11. What was NOT audited

- Statistical/model quality, LOSO/grouped-fold results, and whether the Core ML outputs are scientifically valid.
- Python/FastAPI implementation beyond the Swift client's observable endpoint contracts.
- A real Apple Watch/iPhone run, background execution lifetime, HealthKit authorization, WCSession delivery timing, battery, and thermal behavior.
- Instruments profiling, Energy Log, Network Link Conditioner, Thread Sanitizer, or Accessibility Inspector execution.
- Entitlement/certificate/provisioning correctness beyond visible project/plist declarations.
- App Store privacy nutrition labels and legal privacy-policy completeness.
- Full localization wording quality; only catalog completeness and obvious mixed-language behavior were checked.
- Third-party framework internals and Apple framework implementation details.
- Deep test-coverage measurement; the test target was scanned and compiled, not mutation-tested.
- Unrelated dirty-worktree files outside `watch_streamer`.

## 12. Verification

The fresh compiler ground truth was captured with a clean generic iOS build. It succeeded and produced two source warnings, both cited in §4.1. The full app/Watch build and `ScrybeTests` test bundle also compiled; deployment/provenance Python tests reported 9 passed and 2 environment-dependent skips.

- **§5.1** — open `SensorProbe.swift:25-124` and `WatchScrybeModel.swift:70-120`; the only recorder read is the manual report and the only passive-model construction is inside `WatchParityCheck.run()`. Repository-wide symbol search found no production inference caller.
- **§5.2** — open `ServerCommandListener.swift:460-517`; cancellation/context happen before every `sendMessage`, and its error path queues user-info. Then open `MotionManager.swift:791-816`; report/parity user-info/context copies are explicitly ignored.
- **§5.3** — open `ServerCommandListener.swift:332-353` and `MotionManager.swift:886-901`; probe start has a duration but no command/operation identity or duplicate guard.
- **§5.4** — open `PhoneBridge.swift:269-326`; `receivePayload` returns true after scheduling work, while queue append/persistence occur later. Open `MotionManager.swift:352-377` to see that reply success releases live-delivery responsibility.
- **§3.1** — open the three class declarations and callback ranges cited there; none is annotated `@MainActor`, while each exposes `@Published` state and receives callbacks on non-main executors.
- **§3.2** — open `ServerCommandListener.swift:104-137`; callback code checks/mutates epoch and hello state directly while `connect()` resets them.
- **§6.1** — open the URL construction and plist ATS ranges; schemes are `http/ws`, no authentication headers are attached, and arbitrary loads are enabled.
- **§6.2** — open `PhoneBridge.swift:108-112,497-565` for the Documents queue and `ProfileView.swift:231-237` for the limited reset key list.
- **§8.1** — `sepia` is `#A8893F`; computed WCAG contrast is 2.80:1 on `#F2EBDC` and 2.49:1 on `#E8DEC8`, both below 4.5:1 for normal text.

If a cited issue does not reproduce at its location, re-audit that specific § before implementing rather than silently changing its severity.
