# TARS Roadmap: Event-Driven Voice UX + Stopword Handoff

## Problem Statement
Current interaction has two major issues:
1. Copilot internals are opaque unless reading raw JSON, which makes TARS feel like a black box.
2. The prior `working/handoff` JSON contract is inconsistent and unsafe for TTS (JSON being spoken aloud).

You want a new interaction model where:
- TARS can narrate what Copilot is doing in real time.
- Terminal output is human-readable (not raw JSON spam).
- Handoff is controlled by a voice **stopword**, not final-message JSON protocol.
- There is no `SPEAKING` state gate; speech can happen whenever relevant Copilot events arrive.
- TARS must not transcribe/satisfy its own TTS as user input.

---

## Target Runtime Behavior
1. Wake phrase activates assistant as today.
2. Copilot events (turn start, tool start, deltas, finals) are transformed into readable terminal logs and selective spoken updates.
3. TTS can play at any time new speech-worthy data arrives.
4. User can say stopword (same style as wake detection) to interrupt/hand back to listening mode.
5. Assistant speech never loops back into STT as false user input.

---

## Architecture Changes (High-Level)

### A) Replace protocol-based handoff with stopword-based control
- Remove mandatory `working/handoff` contract dependency from bootstrap behavior.
- Keep normal assistant final text as plain language output.
- Add stopword detection path that can interrupt current copilot turn and force transition to `LISTENING`.

### B) Introduce a Copilot event normalization layer
- Normalize both subprocess JSONL and ACP `session/update` events into a single internal envelope:
  - `turn_start`
  - `message_delta`
  - `message_final`
  - `tool_start`
  - `tool_complete`
  - `turn_end`
  - `error`
- This layer is the source for both terminal narration and TTS planning.

### C) Add a readable terminal event renderer
- Convert raw events into concise, stable lines, for example:
  - `TURN START: planning repo scan`
  - `TOOL START: view README.md`
  - `TOOL DONE: view (32 lines)`
  - `ASSISTANT PARTIAL: "..."`
  - `ASSISTANT FINAL: "..."`
- Keep debug metadata available behind optional verbose flag, but default to readable summaries.

### D) Add a speech arbitration layer
- Decide what should be spoken, when, and how often.
- Priority order:
  1. turn-start acknowledgment (short local phrase)
  2. tool-start action narration
  3. condensed message deltas
  4. brief tool-complete outcomes
  5. final answer remainder
- Enforce dedupe + debounce + rate-limit so voice stays informative, not noisy.

---

## State/Control Model Update

### Proposed state simplification
- Keep existing core states but remove the dependency on `SPEAKING` as a routing gate.
- Speech output becomes an event-driven side effect, not a state transition requirement.
- Stopword always acts as an interrupt route to `LISTENING`.

### Stopword behavior
- Add config:
  - `TARS_STOPWORD_PHRASE`
  - `TARS_STOPWORD_ALIASES`
  - `TARS_STOPWORD_MATCH_PARTIAL`
  - `TARS_STOPWORD_COOLDOWN_MS`
- Detection strategy should mirror wake-word strategy (local phrase detector + aliases), but active during assistant work mode.
- On detection:
  1. cancel/interrupt current copilot turn
  2. flush pending assistant TTS queue
  3. move to `LISTENING`
  4. play brief confirmation cue (optional)

---

## Anti Self-Listening Plan (Critical)

Because speech can happen while listening is active, add layered protection:

1. **Playback gate (already present, strengthen)**
   - Block STT ingestion while TTS is actively playing and for configurable hold time after playback.

2. **Transcript de-echo memory (already present, strengthen)**
   - Keep rolling recent assistant-spoken text windows.
   - Reject STT hypotheses with strong normalized overlap/fuzzy similarity against recent spoken windows.

3. **Intent-aware STT acceptance**
   - During active copilot work, accept only:
     - stopword detections
     - explicit interruption commands
   - Treat all other transcripts as likely echo/noise unless confidence and timing checks pass.

4. **Guard window after each spoken chunk**
   - Short post-playback suppression interval before normal STT acceptance resumes.

5. **Observability for false positives**
   - Log dropped transcripts with reason tags:
     - `dropped:playback_gate`
     - `dropped:deecho_match`
     - `dropped:stopword_only_mode`

---

## Copilot JSON Responses to Exploit Next

For narration/speech:
- `assistant.turn_start`
- `assistant.message_delta`
- `assistant.message`
- `tool.execution_start`
- `tool.execution_complete`
- `assistant.turn_end`

For diagnostics/telemetry only:
- `session.*` readiness events
- `result` usage/duration event
- permission/background task updates

---

## Implementation Phases

1. **Phase 1: Event normalization + readable logs**
   - Build normalized event model.
   - Route existing subprocess/ACP paths through it.
   - Add human-readable renderer.

2. **Phase 2: Stopword control path**
   - Add stopword config + detection pipeline.
   - Wire interrupt transition to `LISTENING`.
   - Remove protocol-dependent handoff branching.

3. **Phase 3: Speech arbitration rewrite**
   - Introduce event-to-speech planner.
   - Keep final dedupe guarantees.
   - Add rate-limits and minimum semantic chunking.

4. **Phase 4: Anti-self-listening hardening**
   - Tighten gate/de-echo/guard windows.
   - Add explicit “stopword-only” STT mode while assistant is actively speaking/working.

5. **Phase 5: Tuning + telemetry**
   - Add counters/timings for first spoken update, interruptions, dropped echoes, spoken event mix.
   - Tune defaults by live trials.

---

## Config Additions/Changes (Planned)
- Add stopword configs listed above.
- Keep partial chunk controls, with force-flush disabled option.
- Add narration/speech controls:
  - `TARS_SPEAK_TURN_START`
  - `TARS_SPEAK_TOOL_EVENTS`
  - `TARS_SPEECH_DEBOUNCE_MS`
  - `TARS_EVENT_LOG_VERBOSE`

---

## Risks and Mitigations
- **Risk:** Over-talking/noisy UX  
  **Mitigation:** speech arbitration with strict priorities and debounce.
- **Risk:** Missed stopword under noise  
  **Mitigation:** aliases + cooldown + confidence tuning + local cue.
- **Risk:** self-transcription loops  
  **Mitigation:** layered gate + de-echo + stopword-only acceptance mode.
- **Risk:** ACP/subprocess event mismatch  
  **Mitigation:** normalized envelope and shared renderer/planner.

---

## Success Criteria
- User can always understand what TARS is doing from readable terminal logs + short spoken progress.
- No raw protocol JSON is spoken.
- Stopword reliably returns control to listening mode.
- No recurring self-listening loop when TARS speaks while active.
- First spoken feedback occurs quickly and consistently while work is in progress.
