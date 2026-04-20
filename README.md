# Event Marker LSL GUI

A Python Tkinter GUI that sends manual experiment event markers over LSL while continuous streams (e.g., BIOPAC/OpenFace/robot) keep recording.

## Features

- Starts an LSL marker stream on app launch (`ExperimentMarkers`, type `Markers`).
- Participant-based 4-trial counterbalancing (IDs `101-110`).
- Enforced phase-by-phase workflow with button gating.
- Fixed 2-minute baseline segments around all trials:
  - Briefing -> Baseline (2 min) -> Trial 1
  - Baseline (2 min) -> Trial 2
  - Baseline (2 min) -> Trial 3
  - Baseline (2 min) -> Trial 4
  - Final Baseline (2 min)
- General event buttons:
  - Briefing Start / End
  - Baseline Start / End
- Trial event buttons:
  - Trial Start (Leak Check Start)
  - Leak Check End (Visual Inspection Start)
  - Visual Inspection End (Reporting Start)
  - Trial End (Reporting End)
  - During an active trial, button gating is step-based:
    - After Trial Start: Leak Check End + Trial End enabled
    - After Leak Check End: Visual Inspection End + Trial End enabled
- Trial timer starts on trial start.
- Trial auto-ends (and sends marker) when timer reaches `00:00` if not manually ended.
- Trial audio notifications announce remaining time once at checkpoints:
  - 15-minute trials: 10, 5, and 1 minute remaining
  - 30-minute trials: 20, 10, 5, and 1 minute remaining
- Baseline timer starts on baseline start and auto-ends at `00:00` if not manually ended.
- `Current Trial Info` reflects the active step (briefing, baseline segment, or trial details).
- Reset Controls section:
  - Reset Briefing (only while briefing is active)
  - Reset Baseline (only while baseline is active)
  - Reset Trial (only while trial is active)
  - Resets emit reset markers and return the phase to its pre-start state.
- Custom marker text input.
- Local backup CSV marker log in `marker_logs/`.

## Requirements

- Python 3.9+
- Dependencies in `requirements.txt`

## Installation

```bash
pip install -r requirements.txt
```

## Run

```bash
python Event_marker_LSL_GUI.py
```

## Marker Logging

The app writes local backup logs to:

- `marker_logs/marker_log_YYYYMMDD_HHMMSS.csv`

Columns:

- `wall_time`
- `lsl_time`
- `marker`

## Notes

- `tkinter` is part of standard Python on most desktop installs.
- The app sets `LSLAPICFG` to the project `lsl_api.cfg` so benign liblsl multicast warnings are suppressed.
- Spoken notifications use Windows SAPI via PowerShell first, with `pyttsx3` as fallback.
- Make sure your LabRecorder is running and recording the marker stream together with your other LSL streams.
- LSL markers cannot be deleted after being sent; reset actions send compensating reset markers so aborted attempts can be excluded during analysis.

## Troubleshooting

- If liblsl prints multicast bind warnings for `::1`, confirm `lsl_api.cfg` exists at repo root and includes:
  - `[log]`
  - `level = -2`
- If time cues seem missing, check the on-screen log sequence at a checkpoint:
  - `Audio cue: ...`
  - `Audio queued: ...`
  - `Audio played: ...`
- Timer reliability changes:
  - Countdown uses monotonic clock timing (less drift under UI load).
  - Checkpoints are crossing-based, so a cue still triggers even if exact second boundaries are skipped.
- Hidden timer-speed logic (kept for verification/validation, not shown in GUI):
  - The method `set_timer_speed(speed)` still exists in `Event_marker_LSL_GUI.py`.
  - You can set `self.timer_speed` (or call `self.set_timer_speed(...)`) in code for accelerated dry-runs (for example `10.0` or `50.0`), then restore to `1.0` for real sessions.
