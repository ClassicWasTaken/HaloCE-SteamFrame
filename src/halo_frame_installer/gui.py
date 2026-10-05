"""Threaded Tk wizard. Passwords are used in memory, never saved or logged."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from . import __version__
from .assets import inspect_image, inspect_maps, extract_image, copy_maps
from .ssh import Settings, SSHConnection

SETUP_URL = "https://partner.steamgames.com/doc/steamhardware/steamframe/setup"
SOURCE_URL = "https://github.com/OpenCommunityEdition/OpenCE/pull/85"
CONTROLS = (
    "A  Jump / accept     B  Melee / back     X  Reload / use     Y  Change weapon\n"
    "RT  Fire     LT  Grenade     LB  Change grenade     RB  Flashlight\n"
    "Left stick  Move / click to crouch     Right stick  Turn / click to zoom\n"
    "Menu  Pause     View  Scoreboard     Both grips  Recenter"
)


class App(tk.Tk):
    def __init__(self, state_dir: Path | None = None):
        super().__init__()
        self.title("Halo • Steam Frame Setup")
        self.geometry(f"850x{min(960, max(650, self.winfo_screenheight()-120))}")
        self.minsize(760, 620)
        self.configure(bg="#101827")
        self.state_dir = state_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".config"))) / "HaloFrameInstaller"
        self.state_file = self.state_dir / "hosts.json"
        self.fingerprints = self._load_fingerprints()
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.password_to_redact = ""
        self.host = tk.StringVar(value="frame")
        self.port = tk.StringVar(value="22")
        self.password = tk.StringVar()
        self.source = tk.StringVar()
        self.authorized = tk.BooleanVar()
        self.steam_closed = tk.BooleanVar()
        self.status = tk.StringVar(value="Choose Xbox game data, or repair the installed native game.")
        self.asset_status = tk.StringVar(value="Original Xbox Halo CE .iso / .xiso, or an extracted maps folder")
        self.log_lines: list[str] = []
        self.buttons = []
        self.entries = []
        self.last_result = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(80, self._drain)

    def _load_fingerprints(self):
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#101827")
        style.configure("Card.TFrame", background="#1b2638")
        style.configure("TLabel", background="#1b2638", foreground="#ecf2fc", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#101827", font=("Segoe UI", 24, "bold"))
        style.configure("Sub.TLabel", background="#101827", foreground="#a8b8ce")
        style.configure("Heading.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7))
        style.configure("TCheckbutton", background="#1b2638", foreground="#ecf2fc", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#1b2638")])
        style.configure("Horizontal.TProgressbar", troughcolor="#1b2638", background="#64d4ad")
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg="#101827", highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas, padding=24)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event:canvas.itemconfigure(window, width=event.width))
        self.bind("<MouseWheel>", lambda event:canvas.yview_scroll(-int(event.delta/120), "units"))
        self.canvas = canvas
        ttk.Label(body, text="Halo on Steam Frame", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"Native ARM64 VR • Xbox-style controls • Setup {__version__}", style="Sub.TLabel").pack(anchor="w", pady=(5, 15))

        first = self._card(body, "1   Choose your game data")
        row = ttk.Frame(first, style="Card.TFrame")
        row.pack(fill="x", pady=5)
        ttk.Entry(row, textvariable=self.source, state="readonly").pack(side="left", fill="x", expand=True)
        self._button(row, "Choose ISO", self._choose_iso).pack(side="left", padx=(8, 0))
        self._button(row, "Maps folder", self._choose_maps).pack(side="left", padx=(8, 0))
        ttk.Label(first, textvariable=self.asset_status, wraplength=730).pack(anchor="w", pady=4)
        ttk.Checkbutton(first, text="I am authorized to use this original Xbox game data.", variable=self.authorized).pack(anchor="w", pady=2)

        second = self._card(body, "2   Connect your Frame")
        ttk.Label(second, text="On your Frame: Settings → System → Enable Developer Mode.\nThen Developer → Set User Password. Keep both devices on the same network.", wraplength=730).pack(anchor="w")
        row = ttk.Frame(second, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 4))
        ttk.Label(row, text="Address").pack(side="left")
        self._entry(row, textvariable=self.host, width=20).pack(side="left", padx=(6, 12))
        ttk.Label(row, text="Port").pack(side="left")
        self._entry(row, textvariable=self.port, width=5).pack(side="left", padx=(6, 12))
        ttk.Label(row, text="Password").pack(side="left")
        self._entry(row, textvariable=self.password, show="•", width=20).pack(side="left", padx=6, fill="x", expand=True)
        self._button(row, "Test connection", self._test_connection).pack(side="left", padx=(6, 0))
        ttk.Label(second, text="Login: steamos. Your password stays in memory and is never saved.", foreground="#a8b8ce").pack(anchor="w")
        ttk.Checkbutton(second, text="I have saved and closed games. Setup may briefly restart Steam to add the library entry.", variable=self.steam_closed).pack(anchor="w", pady=(8, 2))

        third = self._card(body, "3   Install and play")
        ttk.Label(third, text="Setup copies your maps, builds the native VR game, applies the controller layout,\nand adds it to Steam. Allow at least 12 GB free on the Frame. The first build can take a while.", wraplength=730).pack(anchor="w")
        ttk.Label(third, text=CONTROLS, foreground="#a8b8ce", font=("Segoe UI", 9)).pack(anchor="w", pady=7)
        row = ttk.Frame(third, style="Card.TFrame")
        row.pack(fill="x")
        self._button(row, "Install native Halo VR", self._install).pack(side="left")
        self._button(row, "Repair installed game", lambda:self._install(repair=True)).pack(side="left", padx=(8, 0))
        self.retry_button = self._button(row, "Add to Steam again", self._retry_steam)
        self.retry_button.pack(side="left", padx=8)
        self.retry_button.configure(state="disabled")
        self.cancel_button = ttk.Button(row, text="Cancel", command=self.cancel.set, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(third, maximum=100)
        self.progress.pack(fill="x", pady=(12, 5))
        ttk.Label(third, textvariable=self.status, wraplength=730).pack(anchor="w")

        bottom = ttk.Frame(body)
        bottom.pack(fill="x", pady=(10, 4))
        ttk.Button(bottom, text="Valve SSH guide", command=lambda:webbrowser.open(SETUP_URL)).pack(side="left")
        ttk.Button(bottom, text="Native VR source", command=lambda:webbrowser.open(SOURCE_URL)).pack(side="left", padx=6)
        ttk.Button(bottom, text="Save setup log", command=self._save_log).pack(side="right")
        self.log = tk.Text(body, height=5, bg="#0b1220", fg="#a8b8ce", relief="flat", font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, pady=(5, 0))

    def _card(self, parent, title):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
        frame.pack(fill="x", pady=(0, 10))
        ttk.Label(frame, text=title, style="Heading.TLabel").pack(anchor="w", pady=(0, 7))
        return frame

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.buttons.append(button)
        return button

    def _entry(self, parent, **kwargs):
        entry = ttk.Entry(parent, **kwargs)
        self.entries.append(entry)
        return entry

    def _choose_iso(self):
        selected = filedialog.askopenfilename(title="Select your original Xbox Halo CE image", filetypes=[("Xbox disc image", "*.iso *.xiso"), ("All files", "*.*")])
        if selected:
            self._inspect(Path(selected))

    def _choose_maps(self):
        selected = filedialog.askdirectory(title="Select your original Xbox Halo CE maps folder")
        if selected:
            self._inspect(Path(selected))

    def _inspect(self, selected):
        if self.busy:
            return
        self._set_busy(True)
        def worker():
            try:
                info = inspect_maps(selected) if selected.is_dir() else inspect_image(selected)
                self.events.put(("asset", str(selected), f"Validated {info.map_count} original Xbox maps • {info.estimated_bytes / 1e9:.2f} GB • {info.build}"))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("idle",))
        threading.Thread(target=worker, daemon=True).start()

    def _settings(self):
        try:
            port = int(self.port.get())
        except ValueError:
            raise ValueError("Enter a numeric SSH port.") from None
        host = self.host.get().strip()
        return Settings(host=host, password=self.password.get(), port=port,
            known_host_fingerprint=self.fingerprints.get(f"{host}:{port}"),
            accept_host_key=lambda h,a,v:self._approve_host(h,a,v,port),
            close_steam_for_shortcut=self.steam_closed.get())

    def _approve_host(self, host, algorithm, value, port):
        ready = threading.Event()
        answer = []
        self.events.put(("fingerprint", host, algorithm, value, port, ready, answer))
        while not ready.wait(0.1):
            if self.cancel.is_set():
                return False
        return bool(answer and answer[0])

    def _set_busy(self, value):
        self.busy = value
        for button in self.buttons:
            button.configure(state="disabled" if value else "normal")
        for entry in self.entries:
            entry.configure(state="disabled" if value else "normal")
        self.retry_button.configure(state="normal" if not value and self.last_result is not None else "disabled")
        self.cancel_button.configure(state="normal" if value else "disabled")
        if value:
            self.cancel.clear()

    def _test_connection(self):
        try:
            settings = self._settings()
        except ValueError as exc:
            messagebox.showerror("Connection details", str(exc), parent=self)
            return
        self.password_to_redact = settings.password
        self._set_busy(True)
        self.status.set("Connecting to your Frame…")
        def worker():
            connection = SSHConnection(settings)
            try:
                connection.connect()
                arch = connection.run(["uname", "-m"], cancel_event=self.cancel).strip()
                if arch not in ("aarch64", "arm64"):
                    raise ValueError("This device is not an ARM64 Steam Frame.")
                self.events.put(("connected", settings.host, settings.port, connection.host_fingerprint))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                connection.close()
                settings.password = ""
                self.events.put(("idle",))
        threading.Thread(target=worker, daemon=True).start()

    def _install(self, repair=False):
        if (not repair and not self.source.get()) or not self.authorized.get():
            messagebox.showinfo("Choose game data", "Confirm that you are authorized to use the installed Xbox game data." if repair else "Choose your original Xbox Halo CE image or maps, and confirm you are authorized to use them.", parent=self)
            return
        if not self.steam_closed.get():
            messagebox.showinfo("Close games first", "Save and close games, then confirm that setup may briefly restart Steam to add the library entry.", parent=self)
            return
        try:
            settings = self._settings()
        except ValueError as exc:
            messagebox.showerror("Connection details", str(exc), parent=self)
            return
        self.password_to_redact = settings.password
        source = Path(self.source.get()) if self.source.get() else None
        if repair:
            data_note = "Your selected Xbox data may replace the installed maps." if source else "Valid installed Xbox maps are kept. If maps are damaged, choose an original Xbox image and retry."
            if not messagebox.askyesno("Repair existing native game", "Setup will check ~/Games/HaloCENativeVR on your Frame and reinstall its native program files and Xbox controls. Saves and unrelated settings are preserved.\n\n" + data_note + "\n\nRepair this installation?", parent=self):
                return
            settings.adopt_existing_native = True
        self._set_busy(True)
        self.status.set("Preparing installation…")
        last_progress = [None, 0.0]
        def report(stage, message, percent=None):
            now = time.monotonic()
            if stage == last_progress[0] and now - last_progress[1] < 0.2 and percent != 100:
                return
            last_progress[:] = [stage, now]
            self.events.put(("progress", stage, str(message), percent))
        def worker():
            from .install import run
            try:
                if source is None:
                    result = run(settings, None, report, self.cancel)
                    self.events.put(("complete", result))
                    return
                info = inspect_maps(source) if source.is_dir() else inspect_image(source)
                if shutil.disk_usage(tempfile.gettempdir()).free < info.estimated_bytes + 512 * 1024**2:
                    raise ValueError("Not enough free temporary space on this computer to prepare the maps.")
                with tempfile.TemporaryDirectory(prefix="halo-frame-") as temporary:
                    extracted = Path(temporary) / "data"
                    progress = lambda message,current,total:report("Preparing maps", message, current * 100 / total if total else None)
                    if source.is_dir():
                        copy_maps(source, extracted, progress=progress, cancel_event=self.cancel)
                    else:
                        extract_image(source, extracted, progress=progress, cancel_event=self.cancel)
                    result = run(settings, extracted / "maps", report, self.cancel)
                self.events.put(("complete", result))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                settings.password = ""
                self.events.put(("clear_password",))
                self.events.put(("idle",))
        threading.Thread(target=worker, daemon=True).start()

    def _retry_steam(self):
        if not self.steam_closed.get():
            messagebox.showinfo("Close games first", "Save and close games, then confirm that setup may restart Steam.", parent=self)
            return
        try:
            settings = self._settings()
        except ValueError as exc:
            messagebox.showerror("Connection details", str(exc), parent=self)
            return
        self.password_to_redact = settings.password
        self._set_busy(True)
        def worker():
            from .install import Installer
            try:
                result = Installer().add_to_steam(settings,
                    lambda s,m,p=None:self.events.put(("progress",s,str(m),p)), self.cancel)
                self.events.put(("complete",result))
            except Exception as exc:
                self.events.put(("error",str(exc)))
            finally:
                settings.password = ""
                self.events.put(("clear_password",)); self.events.put(("idle",))
        threading.Thread(target=worker, daemon=True).start()

    def _append(self, text):
        text = str(text)
        if self.password_to_redact:
            text = text.replace(self.password_to_redact, "[redacted]")
        self.log_lines.append(text)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "asset":
                    self.source.set(event[1]); self.asset_status.set(event[2])
                    self.status.set("Game data validated. Connect your Frame next.")
                elif kind == "fingerprint":
                    _, host, algorithm, value, port, ready, answer = event
                    accepted = messagebox.askyesno("Verify your Frame", f"First connection to {host}.\n\nSSH host key ({algorithm}):\n{value}\n\nCompare this with your Frame's host fingerprint on a trusted connection. Trust this device?", parent=self)
                    answer.append(accepted)
                    if accepted:
                        self._remember(host, port, value)
                    ready.set()
                elif kind == "connected":
                    _, host, port, value = event
                    if value:
                        self._remember(host, port, value)
                    self.status.set("Connected to an ARM64 device. Ready to install.")
                    self._append("SSH connection verified. No password was saved.")
                elif kind == "progress":
                    _, stage, message, percent = event
                    self.status.set(f"{stage}: {message}"[:500])
                    if percent is None:
                        self.progress.configure(mode="indeterminate"); self.progress.start(20)
                    else:
                        self.progress.stop(); self.progress.configure(mode="determinate", value=max(0,min(100,percent)))
                    self._append(f"{stage}: {message}")
                elif kind == "complete":
                    result = event[1]
                    self.last_result = result
                    self.progress.stop(); self.progress.configure(mode="determinate", value=100)
                    action = "repaired" if getattr(result, "repaired", False) else "installed"
                    done = f"Native Halo VR is {action}. Open Steam and launch Halo: Combat Evolved VR (Native)."
                    if getattr(result, "backup_path", None):
                        self._append("Program-file backup: " + result.backup_path)
                    if result.requires_manual_steam_step:
                        done = "Native Halo VR is installed; its Steam entry needs one more step.\n" + result.steam.get("reason", "") + "\n" + result.steam.get("instructions", "Quit Steam, then click Add to Steam again.")
                        self._append("Executable: " + result.game_path + "/halo")
                        self._append("Launch options: " + result.steam.get("launchOptions", "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0 %command%"))
                    self.status.set(done)
                    self._append(done)
                    messagebox.showinfo("Setup complete", done + "\n\nXbox controls and motion aiming are enabled. The native port uses its own multiplayer protocol; legacy PC servers and PC saves are incompatible.", parent=self)
                elif kind == "error":
                    text = event[1].replace(self.password_to_redact, "[redacted]") if self.password_to_redact else event[1]
                    self.status.set("Setup stopped. See the message below; you can retry.")
                    self._append(text)
                    messagebox.showerror("Setup needs attention", text[-4000:], parent=self)
                elif kind == "clear_password":
                    self.password.set(""); self.password_to_redact = ""
                elif kind == "idle":
                    self.progress.stop(); self._set_busy(False)
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _remember(self, host, port, value):
        self.fingerprints[f"{host}:{port}"] = value
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.fingerprints, indent=2), encoding="utf-8")
        except OSError:
            self._append("Could not save the public host fingerprint; it will be requested next time.")

    def _save_log(self):
        path = filedialog.asksaveasfilename(title="Save setup log", defaultextension=".txt", initialfile="halo-frame-setup-log.txt", filetypes=[("Text", "*.txt")])
        if path:
            try:
                Path(path).write_text("\n".join(self.log_lines) + "\n", encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Could not save log", str(exc), parent=self)

    def _close(self):
        if self.busy:
            if messagebox.askyesno("Cancel setup?", "Cancel the current setup? Existing games and saves will be kept.", parent=self):
                self.cancel.set()
                self.status.set("Cancelling… Keep this window open until setup stops.")
            return
        self.password.set("")
        self.destroy()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-report":
        from .install import resources_path
        from .selftest import smoke_test
        report = smoke_test(resources_path())
        Path(sys.argv[2]).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return
    App().mainloop()
