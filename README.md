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
- Trial timer starts on trial start.
- Trial auto-ends (and sends marker) when timer reaches `00:00` if not manually ended.
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
- Make sure your LabRecorder is running and recording the marker stream together with your other LSL streams.
- LSL markers cannot be deleted after being sent; reset actions send compensating reset markers so aborted attempts can be excluded during analysis.
