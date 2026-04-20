import csv
import os
import math
import queue
import subprocess
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# Force liblsl to use the project-local config (silences benign multicast warnings on loopback).
os.environ.setdefault("LSLAPICFG", os.path.join(os.path.dirname(__file__), "lsl_api.cfg"))

from pylsl import StreamInfo, StreamOutlet, local_clock
import pyttsx3


# -----------------------------
# Counterbalancing definitions
# -----------------------------
OPTION_DEFINITIONS = {
    1: {"minutes": 15, "elbows": 2},
    2: {"minutes": 30, "elbows": 2},
    3: {"minutes": 15, "elbows": 4},
    4: {"minutes": 30, "elbows": 4},
}

BASELINE_SECONDS = 120

# Based on the image you shared
PARTICIPANT_TRIAL_MAP = {
    101: [1, 2, 4, 3],
    102: [2, 3, 1, 4],
    103: [3, 4, 2, 1],
    104: [4, 1, 3, 2],
    105: [1, 2, 4, 3],
    106: [2, 3, 1, 4],
    107: [3, 4, 2, 1],
    108: [4, 1, 3, 2],
    109: [1, 2, 4, 3],
    110: [2, 3, 1, 4],
}


class ExperimentMarkerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Experiment LSL Marker GUI")
        self.root.geometry("1200x780")

        # -----------------------------
        # LSL outlet starts immediately
        # -----------------------------
        self.stream_name = "ExperimentMarkers"
        self.stream_type = "Markers"
        self.source_id = f"experiment-markers-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        info = StreamInfo(
            self.stream_name,
            self.stream_type,
            1,
            0,  # irregular event stream
            "string",
            self.source_id,
        )
        self.outlet = StreamOutlet(info)

        # -----------------------------
        # State
        # -----------------------------
        self.participant_id = None
        self.trial_sequence = []
        self.current_trial_index = 0  # 0-based, so trial number is +1
        self.trial_active = False
        self.timer_running = False
        self.remaining_seconds = 0
        self.timer_job = None
        self.timer_mode = None
        self.timer_end_monotonic = None
        self.last_remaining_seconds = None
        self.timer_speed = 1.0

        # local backup log
        self.log_file = self._create_log_file()

        # -----------------------------
        # UI variables
        # -----------------------------
        self.participant_var = tk.StringVar()
        self.participant_status_var = tk.StringVar(value="No participant loaded.")
        self.current_trial_var = tk.StringVar(value="Trial: -")
        self.time_var = tk.StringVar(value="Allocated Time: -")
        self.elbow_var = tk.StringVar(value="Configuration: -")
        self.timer_var = tk.StringVar(value="00:00")
        self.last_marker_var = tk.StringVar(value="Last Marker: None")
        self.custom_event_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self.session_phase = "idle"
        self.workflow_phase = "no_participant"

        self.briefing_active = False
        self.baseline_active = False
        self.notes_file = None
        self.current_trial_started = False
        self.trial_step = None
        self.trial_alert_checkpoints = {}
        self.announced_time_alerts = set()
        self.voice_queue = queue.Queue()
        self.voice_thread = None
        self._init_voice_engine()

        self._build_ui()

        # Send app-start marker
        self.send_marker("gui_started")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -----------------------------
    # File logging
    # -----------------------------
    def _create_log_file(self) -> str:
        logs_dir = "marker_logs"
        os.makedirs(logs_dir, exist_ok=True)
        filename = datetime.now().strftime("marker_log_%Y%m%d_%H%M%S.csv")
        filepath = os.path.join(logs_dir, filename)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["wall_time", "lsl_time", "marker"])

        return filepath

    def append_local_log(self, marker: str, lsl_time: float) -> None:
        with open(self.log_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(timespec="milliseconds"),
                f"{lsl_time:.6f}",
                marker
            ])

    # -----------------------------
    # UI
    # -----------------------------
    def _build_ui(self) -> None:
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        y_scroll = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        y_scroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=y_scroll.set)

        main = ttk.Frame(self.canvas, padding=12)
        self.main_window = self.canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", self._on_main_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Top frame
        top = ttk.Frame(main)
        top.pack(fill="x", pady=(0, 10))

        participant_frame = ttk.LabelFrame(top, text="Participant Setup", padding=10)
        participant_frame.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Label(participant_frame, text="Participant ID:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(participant_frame, textvariable=self.participant_var, width=15).grid(row=0, column=1, sticky="w", padx=5, pady=5)
        ttk.Button(participant_frame, text="Load Participant", command=self.load_participant).grid(row=0, column=2, sticky="w", padx=5, pady=5)

        ttk.Label(participant_frame, textvariable=self.participant_status_var).grid(row=1, column=0, columnspan=3, sticky="w", padx=5, pady=5)

        info_frame = ttk.LabelFrame(top, text="Current Trial Info", padding=10)
        info_frame.pack(side="left", fill="x", expand=True)

        ttk.Label(info_frame, textvariable=self.current_trial_var, font=("Arial", 12, "bold")).grid(row=0, column=0, sticky="w", padx=5, pady=4)
        ttk.Label(info_frame, textvariable=self.time_var, font=("Arial", 12)).grid(row=1, column=0, sticky="w", padx=5, pady=4)
        ttk.Label(info_frame, textvariable=self.elbow_var, font=("Arial", 12)).grid(row=2, column=0, sticky="w", padx=5, pady=4)

        timer_frame = ttk.LabelFrame(main, text="Timer", padding=10)
        timer_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(timer_frame, textvariable=self.timer_var, font=("Arial", 28, "bold")).pack(anchor="center", pady=5)

        # General event buttons
        general_frame = ttk.LabelFrame(main, text="General Events", padding=10)
        general_frame.pack(fill="x", pady=(0, 10))

        self.briefing_start_btn = ttk.Button(general_frame, text="Briefing Start", command=self.briefing_start)
        self.briefing_start_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.briefing_end_btn = ttk.Button(general_frame, text="Briefing End", command=self.briefing_end)
        self.briefing_end_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.baseline_start_btn = ttk.Button(general_frame, text="Baseline Start", command=self.baseline_start)
        self.baseline_start_btn.grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        self.baseline_end_btn = ttk.Button(general_frame, text="Baseline End", command=self.baseline_end)
        self.baseline_end_btn.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        for i in range(4):
            general_frame.columnconfigure(i, weight=1)

        # Trial buttons
        trial_frame = ttk.LabelFrame(main, text="Trial Events", padding=10)
        trial_frame.pack(fill="x", pady=(0, 10))

        self.trial_start_btn = ttk.Button(
            trial_frame,
            text="Trial Start (Leak Check Start)",
            command=self.start_trial
        )
        self.trial_start_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.leak_check_end_btn = ttk.Button(
            trial_frame,
            text="Leak Check End (Visual Inspection Start)",
            command=self.leak_check_end
        )
        self.leak_check_end_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.visual_inspection_end_btn = ttk.Button(
            trial_frame,
            text="Visual Inspection End (Reporting Start)",
            command=self.visual_inspection_end
        )
        self.visual_inspection_end_btn.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

        self.trial_end_btn = ttk.Button(
            trial_frame,
            text="Trial End (Reporting End)",
            command=self.end_trial_manual
        )
        self.trial_end_btn.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        for i in range(4):
            trial_frame.columnconfigure(i, weight=1)

        # Custom event
        custom_frame = ttk.LabelFrame(main, text="Custom Event", padding=10)
        custom_frame.pack(fill="x", pady=(0, 10))

        ttk.Entry(custom_frame, textvariable=self.custom_event_var).grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        ttk.Button(custom_frame, text="Send Custom Event", command=self.send_custom_event).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        custom_frame.columnconfigure(0, weight=1)

        notes_frame = ttk.LabelFrame(main, text="Researcher Notes (Press Enter to Save)", padding=10)
        notes_frame.pack(fill="x", pady=(0, 10))
        self.notes_entry = ttk.Entry(notes_frame, textvariable=self.note_var)
        self.notes_entry.pack(fill="x")
        self.notes_entry.bind("<Return>", self.save_note_from_enter)

        reset_frame = ttk.LabelFrame(main, text="Reset Controls", padding=10)
        reset_frame.pack(fill="x", pady=(0, 10))

        self.reset_briefing_btn = ttk.Button(reset_frame, text="Reset Briefing", command=self.reset_briefing)
        self.reset_briefing_btn.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.reset_baseline_btn = ttk.Button(reset_frame, text="Reset Baseline", command=self.reset_baseline)
        self.reset_baseline_btn.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.reset_trial_btn = ttk.Button(reset_frame, text="Reset Trial", command=self.reset_trial)
        self.reset_trial_btn.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

        for i in range(3):
            reset_frame.columnconfigure(i, weight=1)

        # Status / log
        status_frame = ttk.LabelFrame(main, text="Status", padding=10)
        status_frame.pack(fill="both", expand=True)

        ttk.Label(status_frame, textvariable=self.last_marker_var, font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 8))

        self.log_text = tk.Text(status_frame, height=18, wrap="word")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

        self._refresh_button_states()

    # -----------------------------
    # Utility
    # -----------------------------
    def _on_main_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.main_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def log_message(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def send_marker(self, marker: str) -> None:
        lsl_time = local_clock()
        self.outlet.push_sample([marker], timestamp=lsl_time)
        self.append_local_log(marker, lsl_time)
        self.last_marker_var.set(f"Last Marker: {marker}")
        self.log_message(f"Sent marker: {marker} | LSL time: {lsl_time:.6f}")

    def _format_mmss(self, total_seconds: int) -> str:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _compute_remaining_seconds(self) -> int:
        if self.timer_end_monotonic is None:
            return self.remaining_seconds
        real_seconds_left = max(0.0, self.timer_end_monotonic - time.monotonic())
        experiment_seconds_left = real_seconds_left * self.timer_speed
        return max(0, int(math.ceil(experiment_seconds_left)))

    def set_timer_speed(self, speed: float) -> None:
        speed = max(0.1, float(speed))
        if self.timer_running and self.timer_end_monotonic is not None:
            remaining = self._compute_remaining_seconds()
            self.timer_speed = speed
            self.timer_end_monotonic = time.monotonic() + (remaining / self.timer_speed)
            self.remaining_seconds = remaining
            self.timer_var.set(self._format_mmss(self.remaining_seconds))
            self.log_message(f"Timer speed set to {self.timer_speed:g}x")
            return

        self.timer_speed = speed
        self.log_message(f"Timer speed set to {self.timer_speed:g}x")

    def _init_voice_engine(self):
        self.voice_thread = threading.Thread(target=self._voice_worker, daemon=True)
        self.voice_thread.start()

    def _voice_worker(self) -> None:
        while True:
            text = self.voice_queue.get()
            if text is None:
                break
            try:
                if not self._speak_windows_sapi(text):
                    # Fallback path if PowerShell speech is unavailable.
                    engine = pyttsx3.init()
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                self.root.after(0, lambda text=text: self.log_message(f"Audio played: {text}"))
            except Exception as exc:
                err = str(exc)
                self.root.after(0, lambda err=err: self.log_message(f"Voice notification failed: {err}"))

    def _speak_windows_sapi(self, text: str) -> bool:
        # Use native Windows speech synthesis in a short-lived process for robustness.
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Speak([Console]::In.ReadToEnd()); "
            "$s.Dispose()"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            input=text,
            text=True,
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0

    def _speak(self, text: str) -> None:
        self.log_message(f"Audio queued: {text}")
        self.voice_queue.put(text)

    def _set_trial_alert_checkpoints(self, trial_duration_minutes: int) -> None:
        if trial_duration_minutes >= 30:
            minute_checkpoints = [20, 10, 5, 1]
        else:
            minute_checkpoints = [10, 5, 1]

        self.trial_alert_checkpoints = {
            minutes * 60: f"{minutes} minute{'s' if minutes != 1 else ''} remaining"
            for minutes in minute_checkpoints
            if minutes < trial_duration_minutes
        }
        self.announced_time_alerts.clear()

    def _maybe_announce_trial_time_remaining(self) -> None:
        if self.timer_mode != "trial" or not self.trial_alert_checkpoints:
            return

        if self.last_remaining_seconds is None:
            self.last_remaining_seconds = self.remaining_seconds + 1

        crossed = [
            checkpoint
            for checkpoint in self.trial_alert_checkpoints.keys()
            if checkpoint not in self.announced_time_alerts
            and self.last_remaining_seconds > checkpoint >= self.remaining_seconds
        ]
        for checkpoint in sorted(crossed, reverse=True):
            message = self.trial_alert_checkpoints[checkpoint]
            self.announced_time_alerts.add(checkpoint)
            self.log_message(
                f"Audio cue: {message} "
                f"(checkpoint={checkpoint}s, now={self.remaining_seconds}s)"
            )
            self._speak(message)

        self.last_remaining_seconds = self.remaining_seconds

    def _refresh_button_states(self) -> None:
        briefing_start_enabled = self.workflow_phase == "await_briefing_start"
        briefing_end_enabled = self.workflow_phase == "briefing_active"
        baseline_start_enabled = self.workflow_phase == "await_baseline_start"
        baseline_end_enabled = self.workflow_phase == "baseline_active"
        trial_start_enabled = self.workflow_phase == "await_trial_start"
        in_trial = self.workflow_phase == "trial_active"
        leak_check_end_enabled = in_trial and self.trial_step == "leak_check"
        visual_inspection_end_enabled = in_trial and self.trial_step == "visual_inspection"
        reset_briefing_enabled = self.workflow_phase == "briefing_active" and self.briefing_active
        reset_baseline_enabled = self.workflow_phase == "baseline_active" and self.baseline_active
        reset_trial_enabled = self.workflow_phase == "trial_active" and self.trial_active and self.current_trial_started

        self.briefing_start_btn.config(state="normal" if briefing_start_enabled else "disabled")
        self.briefing_end_btn.config(state="normal" if briefing_end_enabled else "disabled")
        self.baseline_start_btn.config(state="normal" if baseline_start_enabled else "disabled")
        self.baseline_end_btn.config(state="normal" if baseline_end_enabled else "disabled")

        self.trial_start_btn.config(state="normal" if trial_start_enabled else "disabled")
        self.leak_check_end_btn.config(state="normal" if leak_check_end_enabled else "disabled")
        self.visual_inspection_end_btn.config(state="normal" if visual_inspection_end_enabled else "disabled")
        self.trial_end_btn.config(state="normal" if in_trial else "disabled")
        self.reset_briefing_btn.config(state="normal" if reset_briefing_enabled else "disabled")
        self.reset_baseline_btn.config(state="normal" if reset_baseline_enabled else "disabled")
        self.reset_trial_btn.config(state="normal" if reset_trial_enabled else "disabled")

    def _current_baseline_tag(self) -> str:
        if self.current_trial_index < 4:
            return f"pre_t{self.current_trial_index + 1}"
        return "post_t4"

    def _get_current_trial_info(self):
        if self.participant_id is None or self.current_trial_index >= 4:
            return None

        trial_number = self.current_trial_index + 1
        option_number = self.trial_sequence[self.current_trial_index]
        option_info = OPTION_DEFINITIONS[option_number]

        return {
            "trial_number": trial_number,
            "option_number": option_number,
            "minutes": option_info["minutes"],
            "elbows": option_info["elbows"],
        }

    def update_trial_display(self) -> None:
        info = self._get_current_trial_info()
        if self.participant_id is None:
            self.current_trial_var.set("Step: Participant Not Loaded")
            self.time_var.set("Allocated Time: -")
            self.elbow_var.set("Configuration: -")
            if not self.trial_active:
                self.timer_var.set("00:00")
            return

        if self.workflow_phase in {"await_briefing_start", "briefing_active"}:
            self.current_trial_var.set("Step: Briefing")
            self.time_var.set("Allocated Time: -")
            self.elbow_var.set("Configuration: -")
            return

        if self.workflow_phase in {"await_baseline_start", "baseline_active"}:
            tag = self._current_baseline_tag()
            self.current_trial_var.set(f"Step: Baseline ({tag})")
            self.time_var.set("Allocated Time: 2 minutes")
            self.elbow_var.set("Configuration: -")
            return

        if info is None:
            self.current_trial_var.set("Step: Completed")
            self.time_var.set("Allocated Time: -")
            self.elbow_var.set("Configuration: -")
            if not self.trial_active:
                self.timer_var.set("00:00")
            return

        self.current_trial_var.set(f"Trial: {info['trial_number']}")
        self.time_var.set(f"Allocated Time: {info['minutes']} minutes")
        self.elbow_var.set(f"Configuration: {info['elbows']} elbows")

    # -----------------------------
    # Participant loading
    # -----------------------------
    def load_participant(self) -> None:
        raw = self.participant_var.get().strip()

        if not raw.isdigit():
            messagebox.showerror("Invalid Input", "Participant ID must be numeric.")
            return

        pid = int(raw)

        if pid not in PARTICIPANT_TRIAL_MAP:
            messagebox.showerror(
                "Participant Not Found",
                "Participant ID is not in the current counterbalancing table.\n"
                "Currently supported: 101-110."
            )
            return

        # Reset current session state for new participant
        self.stop_timer()
        self.participant_id = pid
        self.trial_sequence = PARTICIPANT_TRIAL_MAP[pid]
        self.current_trial_index = 0
        self.trial_active = False
        self.briefing_active = False
        self.baseline_active = False
        self.current_trial_started = False
        self.trial_step = None
        self.workflow_phase = "await_briefing_start"
        self.notes_file = self._prepare_notes_file(pid)

        self.participant_status_var.set(
            f"Participant {pid} loaded. Trial order: {self.trial_sequence}"
        )
        self.update_trial_display()
        self._refresh_button_states()

        self.send_marker(f"participant_loaded_p{pid}")
        self.log_message(f"Loaded participant {pid} with trial order {self.trial_sequence}")

    # -----------------------------
    # General events
    # -----------------------------
    def briefing_start(self) -> None:
        if self.workflow_phase != "await_briefing_start":
            return
        self.briefing_active = True
        self.workflow_phase = "briefing_active"
        self.session_phase = "briefing"
        self._refresh_button_states()
        self.update_trial_display()
        self.general_event("briefing_start")

    def briefing_end(self) -> None:
        if self.workflow_phase != "briefing_active":
            return
        self.briefing_active = False
        self.workflow_phase = "await_baseline_start"
        self.session_phase = "awaiting_baseline"
        self._refresh_button_states()
        self.update_trial_display()
        self.general_event("briefing_end")

    def reset_briefing(self) -> None:
        if self.workflow_phase != "briefing_active" or not self.briefing_active:
            return
        self.briefing_active = False
        self.workflow_phase = "await_briefing_start"
        self.session_phase = "awaiting_briefing"
        self.general_event("briefing_reset")
        self.log_message("Briefing reset. You can start briefing again.")
        self._refresh_button_states()
        self.update_trial_display()

    def baseline_start(self) -> None:
        if self.workflow_phase != "await_baseline_start":
            return
        self.baseline_active = True
        self.workflow_phase = "baseline_active"
        tag = self._current_baseline_tag()
        self.session_phase = f"baseline_{tag}"
        self._refresh_button_states()
        self.update_trial_display()
        self.general_event(f"baseline_{tag}_start")
        self.start_timer(BASELINE_SECONDS, mode="baseline")

    def baseline_end(self) -> None:
        self._end_baseline(auto=False)

    def _end_baseline(self, auto: bool) -> None:
        if self.workflow_phase != "baseline_active":
            return

        tag = self._current_baseline_tag()
        end_kind = "auto" if auto else "manual"
        self.general_event(f"baseline_{tag}_end_{end_kind}")

        self.stop_timer()
        self.baseline_active = False

        if self.current_trial_index < 4:
            self.workflow_phase = "await_trial_start"
            self.session_phase = f"awaiting_trial_t{self.current_trial_index + 1}"
        else:
            self.workflow_phase = "completed"
            self.session_phase = "completed"
            self.log_message("Participant flow completed (including final baseline).")
            messagebox.showinfo("Participant Complete", "All 4 trials and baselines are complete.")

        self._refresh_button_states()
        self.update_trial_display()

    def reset_baseline(self) -> None:
        if self.workflow_phase != "baseline_active" or not self.baseline_active:
            return
        tag = self._current_baseline_tag()
        self.stop_timer()
        self.baseline_active = False
        self.workflow_phase = "await_baseline_start"
        self.session_phase = "awaiting_baseline"
        self.general_event(f"baseline_{tag}_reset")
        self.log_message(f"Baseline {tag} reset. You can start baseline again.")
        self._refresh_button_states()
        self.update_trial_display()

    def general_event(self, event_name: str) -> None:
        if self.participant_id is not None:
            marker = f"p{self.participant_id}_{event_name}"
        else:
            marker = event_name
        self.send_marker(marker)

    def _prepare_notes_file(self, participant_id: int) -> str:
        notes_root = "researcher_notes"
        participant_dir = os.path.join(notes_root, f"p{participant_id}")
        os.makedirs(participant_dir, exist_ok=True)
        filepath = os.path.join(participant_dir, f"p{participant_id}_notes.csv")
        if not os.path.exists(filepath):
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["wall_time", "participant_id", "phase", "note"])
        else:
            with open(filepath, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
            if rows:
                header = rows[0]
                if "phase" not in header:
                    migrated_rows = [["wall_time", "participant_id", "phase", "note"]]
                    for row in rows[1:]:
                        if len(row) >= 3:
                            migrated_rows.append([row[0], row[1], "", row[2]])
                    with open(filepath, "w", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerows(migrated_rows)
        return filepath

    def save_note_from_enter(self, _event=None):
        note = self.note_var.get().strip()
        if not note:
            return "break"
        if self.participant_id is None:
            messagebox.showwarning("No Participant", "Load a participant before saving notes.")
            return "break"
        if self.notes_file is None:
            self.notes_file = self._prepare_notes_file(self.participant_id)

        with open(self.notes_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(timespec="milliseconds"),
                self.participant_id,
                self.session_phase,
                note,
            ])

        self.log_message(f"Saved note for p{self.participant_id}: {note}")
        self.note_var.set("")
        return "break"

    def send_custom_event(self) -> None:
        text = self.custom_event_var.get().strip()
        if not text:
            messagebox.showwarning("Empty Custom Event", "Please enter custom event text.")
            return

        cleaned = text.lower().replace(" ", "_")
        if self.participant_id is not None:
            marker = f"p{self.participant_id}_custom_{cleaned}"
        else:
            marker = f"custom_{cleaned}"

        self.send_marker(marker)

    # -----------------------------
    # Trial lifecycle
    # -----------------------------
    def start_trial(self) -> None:
        if self.participant_id is None:
            messagebox.showwarning("No Participant", "Load a participant before starting a trial.")
            return

        if self.workflow_phase != "await_trial_start":
            return

        if self.trial_active:
            messagebox.showinfo("Trial Active", "A trial is already running.")
            return

        info = self._get_current_trial_info()
        if info is None:
            messagebox.showinfo("All Trials Completed", "No remaining trials for this participant.")
            return

        self.trial_active = True
        self.current_trial_started = True
        self.trial_step = "leak_check"
        self._set_trial_alert_checkpoints(info["minutes"])
        self.workflow_phase = "trial_active"
        self.session_phase = f"trial_t{info['trial_number']}_leak_check"
        self._refresh_button_states()
        self.update_trial_display()

        trial_num = info["trial_number"]
        option_num = info["option_number"]
        minutes = info["minutes"]
        elbows = info["elbows"]

        marker = (
            f"p{self.participant_id}_trial_start_t{trial_num}_"
            f"option{option_num}_{minutes}min_{elbows}elbows"
        )
        self.send_marker(marker)
        self.log_message(
            f"Trial {trial_num} started | option={option_num}, duration={minutes} min, elbows={elbows}"
        )

        self.start_timer(minutes * 60, mode="trial")

    def leak_check_end(self) -> None:
        if not self.trial_active:
            messagebox.showwarning("No Active Trial", "Start a trial first.")
            return
        if self.trial_step != "leak_check":
            return

        info = self._get_current_trial_info()
        if info is None:
            return

        marker = f"p{self.participant_id}_leak_check_end_t{info['trial_number']}"
        self.trial_step = "visual_inspection"
        self.session_phase = f"trial_t{info['trial_number']}_visual_inspection"
        self.send_marker(marker)
        self._refresh_button_states()

    def visual_inspection_end(self) -> None:
        if not self.trial_active:
            messagebox.showwarning("No Active Trial", "Start a trial first.")
            return
        if self.trial_step != "visual_inspection":
            return

        info = self._get_current_trial_info()
        if info is None:
            return

        marker = f"p{self.participant_id}_visual_inspection_end_t{info['trial_number']}"
        self.trial_step = "reporting"
        self.session_phase = f"trial_t{info['trial_number']}_reporting"
        self.send_marker(marker)
        self._refresh_button_states()

    def end_trial_manual(self) -> None:
        self._end_trial(auto=False)

    def _end_trial(self, auto: bool) -> None:
        if not self.trial_active:
            return

        info = self._get_current_trial_info()
        if info is None:
            return

        trial_num = info["trial_number"]
        option_num = info["option_number"]
        end_kind = "auto" if auto else "manual"

        marker = f"p{self.participant_id}_trial_end_t{trial_num}_option{option_num}_{end_kind}"
        self.send_marker(marker)

        self.stop_timer()
        self.trial_active = False
        self.current_trial_started = False
        self.trial_step = None
        self.trial_alert_checkpoints = {}
        self.announced_time_alerts.clear()
        self.workflow_phase = "await_baseline_start"
        self.session_phase = "awaiting_baseline"
        self.current_trial_index += 1

        self.update_trial_display()
        self._refresh_button_states()

        if self.current_trial_index >= 4:
            self.log_message("Trial 4 complete. Run final 2-minute baseline to finish participant flow.")

    def reset_trial(self) -> None:
        if self.workflow_phase != "trial_active" or not self.trial_active:
            return

        info = self._get_current_trial_info()
        if info is None:
            return

        trial_num = info["trial_number"]
        option_num = info["option_number"]

        self.stop_timer()
        self.trial_active = False
        self.current_trial_started = False
        self.trial_step = None
        self.trial_alert_checkpoints = {}
        self.announced_time_alerts.clear()
        self.workflow_phase = "await_trial_start"
        self.session_phase = f"awaiting_trial_t{trial_num}"
        self.send_marker(f"p{self.participant_id}_trial_reset_t{trial_num}_option{option_num}")
        self.log_message(f"Trial {trial_num} reset. You can start this trial again.")
        self.update_trial_display()
        self._refresh_button_states()

    # -----------------------------
    # Timer
    # -----------------------------
    def start_timer(self, seconds: int, mode: str) -> None:
        self.stop_timer()
        self.remaining_seconds = max(0, int(seconds))
        self.timer_mode = mode
        self.timer_end_monotonic = time.monotonic() + (self.remaining_seconds / self.timer_speed)
        self.last_remaining_seconds = self.remaining_seconds + 1
        self.timer_var.set(self._format_mmss(self.remaining_seconds))
        self.timer_running = True
        self._tick_timer()

    def stop_timer(self) -> None:
        self.timer_running = False
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None
        self.timer_mode = None
        self.timer_end_monotonic = None
        self.last_remaining_seconds = None

    def _tick_timer(self) -> None:
        if not self.timer_running:
            return

        self.remaining_seconds = self._compute_remaining_seconds()

        self._maybe_announce_trial_time_remaining()
        self.timer_var.set(self._format_mmss(self.remaining_seconds))

        if self.remaining_seconds <= 0:
            self.timer_running = False
            self.timer_job = None
            timer_mode = self.timer_mode
            self.timer_mode = None
            if timer_mode == "trial":
                self.log_message("Timer reached 00:00. Ending trial automatically.")
                self._end_trial(auto=True)
            elif timer_mode == "baseline":
                self.log_message("Timer reached 00:00. Ending baseline automatically.")
                self._end_baseline(auto=True)
            return

        self.timer_job = self.root.after(200, self._tick_timer)

    # -----------------------------
    # App lifecycle
    # -----------------------------
    def on_close(self) -> None:
        self.stop_timer()
        self.voice_queue.put(None)
        try:
            self.send_marker("gui_closed")
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ExperimentMarkerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
