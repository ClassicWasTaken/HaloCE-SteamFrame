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
from .assets import ExtractionCancelled, inspect_image, inspect_maps, extract_image, copy_maps
from .ssh import CancelledError, Settings, SSHConnection
from .music import MenuMusic
from .progress import SetupProgress
from .ui import (BG, SIDEBAR, SURFACE, TEXT, MUTED, BORDER,
                 INSET, ACCENT, DISABLED, Button, Card, Page, Choice, power_orb)

SETUP_URL = "https://partner.steamgames.com/doc/steamhardware/steamframe/setup"
PLATFORM_TOOLS_URL = "https://developer.android.com/tools/releases/platform-tools"
SOURCE_URL = "https://github.com/OpenCommunityEdition/OpenCE/pull/85"
APP_TITLE = "Halo • Steam Frame VR Mod Installer"
EXPERIMENTAL_NOTICE = (
    "LAN/online campaign, head-directed walking, and render-rate reticle.\n"
    "Upgrades the native game; old saves are kept. Older checkpoints cannot be loaded.\n"
    "Campaign uses one player per machine; co-op partners need matching builds."
)
CONTENT_DISCLOSURE = "No retail game executable, ISO, maps, product keys, or soundtrack is provided."
ARTWORK_CREDIT = "Halo artwork is included. Halo artwork and trademarks belong to Microsoft."
XBOX_REVISION_NOTE = "Original Xbox USA Rev 2 validated; other retail revisions are checked automatically."
GAME_CLOSE_NOTE = "Save and close running games before changing Halo files. Keep Steam Home and SteamVR running."
STEAM_ADD_NOTE = ("In Steam, choose Add a Game → Add a Non-Steam Game and select the native halo executable. "
                  "Use the displayed launch options, then click Add to Steam again to retry available library setup.")
STEAM_ART_NOTE = "Use Steam's custom artwork controls to add Halo library art, or click Add to Steam again to retry."
STEAM_NOTES_NOTE = "Use Steam Notes to add the supplied game description, or click Add to Steam again to retry."
STEAM_REMOVE_NOTE = ("Use Steam's Remove Non-Steam Game option for Halo: Combat Evolved VR (Native). "
                     "Retry when library cleanup is available or Steam is already closed.")
CONTROLS = (
    "A  Jump / accept     B  Melee / back     X  Reload / use     Y  Change weapon\n"
    "RT  Fire     LT  Grenade     LB  Change grenade     RB  Flashlight\n"
    "Left stick  Move by head direction / click to crouch     Right stick  Turn / click to zoom\n"
    "Menu  Pause     View  Scoreboard     Both grips  Recenter"
)


class App(tk.Tk):
    def __init__(self, state_dir: Path | None = None):
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
        super().__init__()
        self.title(APP_TITLE)
        width = min(1040, max(900, self.winfo_screenwidth() - 100))
        height = min(720, max(620, self.winfo_screenheight() - 100))
        self.geometry(f"{width}x{height}")
        self.minsize(900, 620)
        self.configure(bg=BG)
        self.state_dir = state_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".config"))) / "HaloFrameInstaller"
        self.state_file = self.state_dir / "hosts.json"
        self.fingerprints = self._load_fingerprints()
        self.events: queue.Queue = queue.Queue()
        self.music = MenuMusic(on_change=lambda text:self.events.put(("music", text)))
        self.cancel = threading.Event()
        self.busy = False
        self.password_to_redact = ""
        self.host = tk.StringVar(value="frame")
        self.port = tk.StringVar(value="22")
        self.transport = tk.StringVar(value="network")
        self.adb_path = tk.StringVar()
        self.usb_serial = tk.StringVar()
        self.password = tk.StringVar()
        self.source = tk.StringVar()
        self.authorized = tk.BooleanVar()
        self.steam_closed = tk.BooleanVar()
        self.mode = tk.StringVar(value="install")
        self.storage_kind = tk.StringVar(value="internal")
        self.storage_id = tk.StringVar(value="internal")
        self.storage_label = tk.StringVar()
        self.storage_note = tk.StringVar(value="Internal storage is selected. SD cards are checked securely on your Frame.")
        self.summary_storage = tk.StringVar()
        self._storage_generation = 0
        self._storage_destinations = {}
        self._storage_picker_ids = {}
        self._storage_inventory_identity = None
        self.keep_saves = tk.BooleanVar(value=True)
        self.current_page = self.current_step = 0
        self.max_page = 0
        self.installing = False
        self.uninstall_committing = False
        self.activity_open = False
        self.advanced_open = False
        self.phase = tk.StringVar(value="READY TO INSTALL")
        self.progress_state = SetupProgress()
        self.progress_label = tk.StringVar(value="0%")
        self.connection_status = tk.StringVar(value="Your password stays in memory and is never saved.")
        self.music_status = tk.StringVar(value="Select game data for menu music.")
        self.source_label = tk.StringVar(value="No game data selected")
        self.summary_source = tk.StringVar()
        self.summary_frame = tk.StringVar()
        self.summary_heading = tk.StringVar(value="INSTALLATION SUMMARY")
        self.summary_data_heading = tk.StringVar(value="GAME DATA")
        self.summary_action_heading = tk.StringVar(value="XBOX CONTROLS")
        self.summary_action = tk.StringVar()
        self.summary_note = tk.StringVar()
        self.step_count = tk.StringVar(value="Step 1 of 3")
        self.status = tk.StringVar(value="Choose Xbox game data, or repair the installed native game.")
        self.asset_status = tk.StringVar(value=XBOX_REVISION_NOTE)
        self.log_lines: list[str] = []
        self.buttons = []
        self.entries = []
        self.checks = []
        self.last_result = None
        self._asset_generation = 0
        self._inspection_cancel = None
        self._build()
        self.source.trace_add("write", lambda *args:self._source_changed())
        self.mode.trace_add("write", lambda *args:self._mode_changed())
        self.transport.trace_add("write", lambda *args:self._transport_changed())
        for variable in (self.host, self.port, self.usb_serial, self.adb_path):
            variable.trace_add("write", lambda *args:self._invalidate_storage())
        self.storage_kind.trace_add("write", lambda *args:self._storage_changed())
        self.keep_saves.trace_add("write", lambda *args:self._update_summary())
        self._apply_icon()
        self.after_idle(self._apply_window_theme)
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
        style.configure("TEntry", fieldbackground=INSET, foreground=TEXT,
                        insertcolor=ACCENT, bordercolor=BORDER,
                        lightcolor="#5B7052", darkcolor="#0B140E",
                        padding=(10, 9), font=("Segoe UI", 10))
        style.map("TEntry", bordercolor=[("focus", ACCENT)],
                  fieldbackground=[("disabled", "#233027")],
                  foreground=[("disabled", DISABLED)])
        style.configure("Storage.TCombobox", fieldbackground=INSET, background=SURFACE,
                        foreground=TEXT, arrowcolor=ACCENT, bordercolor=BORDER,
                        font=("Segoe UI", 10), padding=(10, 9))
        style.map("Storage.TCombobox", fieldbackground=[("readonly", INSET), ("disabled", "#233027")],
                  foreground=[("disabled", DISABLED)], selectbackground=[("readonly", INSET)],
                  selectforeground=[("readonly", TEXT)])
        self.option_add("*TCombobox*Listbox.background", INSET)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        style.configure("TCheckbutton", background=SURFACE, foreground=TEXT,
                        indicatorbackground=INSET, indicatorforeground=ACCENT,
                        indicatorcolor=ACCENT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=INSET,
                        focuscolor=ACCENT, font=("Segoe UI", 10), padding=(0, 5))
        style.map("TCheckbutton", background=[("active", SURFACE)],
                  foreground=[("disabled", DISABLED)],
                  indicatorbackground=[("selected", "#395D22"), ("disabled", "#263027")],
                  indicatorforeground=[("selected", ACCENT), ("disabled", DISABLED)])
        style.configure("Horizontal.TProgressbar", troughcolor=INSET,
                        background="#86BF39", bordercolor=BORDER,
                        lightcolor=ACCENT, darkcolor="#5A8B27", thickness=11)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg=SIDEBAR, width=218)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        tk.Frame(sidebar, bg="#080D09", width=2).pack(side="right", fill="y")
        tk.Frame(sidebar, bg="#62744C", width=1).pack(side="right", fill="y")
        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill="x", padx=23, pady=(28, 0))
        icon = tk.Canvas(brand, bg=SIDEBAR, width=170, height=77,
                         highlightthickness=0, bd=0)
        icon.pack(anchor="w")
        # Static wire grid and luminous core are drawn locally, not copied assets.
        for x in range(-85, 256, 34):
            icon.create_line(85, 39, x, 77, fill="#263827")
        for y in (54, 61, 69, 76):
            icon.create_line(0, y, 170, y, fill="#263827")
        icon.create_line(0, 37, 45, 37, fill="#587540")
        icon.create_line(124, 37, 170, 37, fill="#587540")
        power_orb(icon, 85, 37, 29)
        self._label(brand, "HALO", 25, "bold", color=ACCENT,
                    background=SIDEBAR).pack(anchor="w", pady=(6, 0))
        self._label(brand, "STEAM FRAME VR MOD", 9, "bold", color=TEXT,
                    background=SIDEBAR).pack(anchor="w", pady=(2, 0))
        self._label(brand, f"Version {__version__}", 9, color=MUTED, background=SIDEBAR).pack(anchor="w", pady=(9, 0))
        self._label(sidebar, "INSTALLATION", 8, "bold", MUTED, SIDEBAR).pack(anchor="w", padx=24, pady=(26, 8))
        self.nav_buttons = []
        for index, title in enumerate(("DATA", "CONNECT", "INSTALL")):
            nav = Button(sidebar, f"0{index + 1}   {title}",
                         lambda i=index:self._nav_to(i), width=180,
                         height=45, background=SIDEBAR, subtle=True)
            nav.pack(fill="x", padx=18, pady=3)
            self.nav_buttons.append(nav)
        help_area = tk.Frame(sidebar, bg=SIDEBAR)
        help_area.pack(side="bottom", fill="x", padx=20, pady=23)
        Button(help_area, "Xbox controls", self._show_controls,
               background=SIDEBAR, subtle=True, width=170).pack(anchor="w")
        Button(help_area, "Help & sources", self._show_help,
               background=SIDEBAR, subtle=True, width=170).pack(anchor="w", pady=(2, 0))
        self._label(help_area, textvariable=self.music_status, size=8, color=MUTED,
                    background=SIDEBAR, wraplength=170).pack(anchor="w", padx=9, pady=(4, 10))
        self._label(help_area, "COMMUNITY MOD INSTALLER", 8, color=MUTED,
                    background=SIDEBAR).pack(anchor="w", padx=10)

        main = tk.Frame(self, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        header = tk.Frame(main, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=32, pady=(27, 16))
        ornament = tk.Canvas(header, bg=BG, width=116, height=84,
                              highlightthickness=0, bd=0)
        ornament.pack(side="right", padx=(10, 0))
        for y in range(8, 84, 7):
            ornament.create_line(0, y, 116, y, fill="#1B2A1D")
        for x in (17, 37, 57, 77, 97):
            ornament.create_line(57, 16, x, 84, fill="#233624")
        for size in (24, 35, 45):
            ornament.create_arc(58 - size, 40 - size, 58 + size, 40 + size,
                                 start=15, extent=287, style="arc",
                                 outline="#3D5732", width=1)
        ornament.create_arc(13, -5, 103, 85, start=48, extent=67,
                             style="arc", outline="#86B644", width=2)
        ornament.create_line(32, 40, 83, 40, fill="#6D9442")
        ornament.create_oval(53, 35, 63, 45, fill="#789E3B", outline="")
        self._label(header, textvariable=self.step_count, size=9,
                    weight="bold", color=ACCENT).pack(anchor="w")
        self.page_title = self._label(header, "GAME DATA", 24, "bold")
        self.page_title.pack(anchor="w", pady=(6, 4))
        self.page_subtitle = self._label(header,
            "Install, repair, or uninstall the community VR mod.", 10, color=MUTED)
        self.page_subtitle.pack(anchor="w")
        page_host = tk.Frame(main, bg=BG)
        page_host.grid(row=1, column=0, sticky="nsew", padx=32)
        page_host.columnconfigure(0, weight=1)
        page_host.rowconfigure(0, weight=1)
        self.pages = [Page(page_host) for _ in range(3)]
        for page in self.pages:
            page.grid(row=0, column=0, sticky="nsew")
        self.canvas = self.pages[0].canvas
        self.bind("<MouseWheel>", lambda event:self.pages[self.current_page].wheel(event))
        self._build_data_page(self.pages[0].body)
        self._build_connection_page(self.pages[1].body)
        self._build_install_page(self.pages[2].body)

        footer = tk.Frame(main, bg=BG)
        footer.grid(row=2, column=0, sticky="ew", padx=32, pady=(15, 18))
        tk.Frame(footer, bg="#526544", height=1).pack(fill="x")
        tk.Frame(footer, bg="#060D08", height=1).pack(fill="x", pady=(0, 11))
        row = tk.Frame(footer, bg=BG)
        row.pack(fill="x")
        self.back_button = self._button(row, "Back", self._back)
        self.back_button.pack(side="left")
        self.activity_button = Button(row, "Show activity", self._toggle_activity,
                                      subtle=True, background=BG)
        self.activity_button.pack(side="left", padx=5)
        self.next_button = self.primary_button = self._button(row, "Continue", self._continue, primary=True)
        self.next_button.pack(side="right")
        self.cancel_button = Button(row, "Cancel", self._cancel_setup, background=BG)
        self.cancel_button.configure(state="disabled")
        self.footer_note = self._label(row, "", 9, color=MUTED)
        self.footer_note.pack(side="right", padx=12)

        self.activity_frame = tk.Frame(main, bg=BG)
        self.activity_frame.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 18))
        activity_heading = tk.Frame(self.activity_frame, bg=BG)
        activity_heading.pack(fill="x")
        self._label(activity_heading, "SETUP ACTIVITY", 9, "bold", color=ACCENT).pack(side="left")
        Button(activity_heading, "Save log", self._save_log, background=BG,
               subtle=True, height=31).pack(side="right")
        log_area = tk.Frame(self.activity_frame, bg=BG)
        log_area.pack(fill="x", pady=(5, 0))
        self.log = tk.Text(log_area, height=5, bg=INSET, fg=MUTED,
                           relief="flat", borderwidth=0, highlightthickness=1,
                           highlightbackground=BORDER, highlightcolor=ACCENT,
                           insertbackground=ACCENT, selectbackground="#48682A",
                           selectforeground=TEXT, padx=12, pady=8,
                           font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(side="left", fill="x", expand=True)
        self.activity_scrollbar = tk.Scrollbar(log_area, orient="vertical", command=self.log.yview,
            relief="flat", bd=0, width=12, bg=BORDER, activebackground="#739449",
            troughcolor=INSET, highlightthickness=0)
        self.activity_scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=self.activity_scrollbar.set)
        self.activity_frame.grid_remove()
        self._show_page(0)

    def _label(self, parent, text=None, size=10, weight="normal", color=TEXT,
               background=BG, **kwargs):
        if text is not None:
            kwargs["text"] = text
        label = tk.Label(parent, bg=background, fg=color, font=("Segoe UI", size, weight),
                         anchor="w", justify="left", **kwargs)
        if "wraplength" in kwargs:
            limit = kwargs["wraplength"]
            parent.bind("<Configure>", lambda event:label.configure(
                wraplength=max(120, min(limit, event.width - 4))), add="+")
        return label

    def _card(self, parent, title=None):
        card = Card(parent, padding=16)
        card.pack(fill="x", pady=(0, 10))
        if title:
            self._label(card.content, title, 12, "bold", background=SURFACE).pack(anchor="w", pady=(0, 8))
        return card.content

    def _button(self, parent, text, command, **kwargs):
        button = Button(parent, text, command, background=parent.cget("background"), **kwargs)
        self.buttons.append(button)
        return button

    def _entry(self, parent, **kwargs):
        entry = ttk.Entry(parent, **kwargs)
        self.entries.append(entry)
        return entry

    def _check(self, parent, text, variable):
        check = ttk.Checkbutton(parent, text=text, variable=variable)
        self.checks.append(check)
        return check

    def _build_data_page(self, body):
        mode_card = self._card(body, "SELECT OPERATION")
        choices = tk.Frame(mode_card, bg=SURFACE)
        choices.pack(fill="x")
        choices.columnconfigure((0, 1, 2), weight=1, uniform="operations")
        self.mode_choices = []
        for index, title, subtitle, value in (
            (0, "Install", "Install or upgrade", "install"),
            (1, "Repair", "Refresh files", "repair"),
            (2, "Uninstall", "Remove game", "uninstall")):
            choice = Choice(choices, title, subtitle, self.mode, value, self._mode_changed)
            choice.grid(row=0, column=index, sticky="ew",
                        padx=(0, 6) if index == 0 else (6, 0) if index == 2 else (6, 6))
            self.mode_choices.append(choice)

        data_panel = self._card(body)
        self.data_panel = data_panel.master
        data_panel.columnconfigure(1, weight=1)
        cover_frame = tk.Frame(data_panel, bg=INSET, highlightbackground=BORDER,
                               highlightthickness=1)
        cover_frame.grid(row=0, column=0, sticky="n", padx=(0, 16))
        try:
            from .install import resources_path
            self._game_cover = tk.PhotoImage(file=str(
                resources_path() / "artwork" / "halo-ce-thumbnail.png")).subsample(2)
            tk.Label(cover_frame, image=self._game_cover, bg=INSET,
                     bd=0).pack(padx=3, pady=3)
        except (OSError, tk.TclError):
            self._label(cover_frame, "HALO\nCOMBAT\nEVOLVED", 10, "bold",
                        color=ACCENT, background=INSET).pack(padx=9, pady=28)
        data = tk.Frame(data_panel, bg=SURFACE)
        data.grid(row=0, column=1, sticky="nsew")
        self.data_title = self._label(data, "Your original Xbox game data", 12, "bold", background=SURFACE)
        self.data_title.pack(anchor="w")
        self.data_note = self._label(data,
            "Choose a disc image or an extracted maps folder.", 10, color=MUTED, background=SURFACE)
        self.data_note.pack(anchor="w", pady=(5, 14))
        file_row = tk.Frame(data, bg=INSET, highlightbackground=BORDER, highlightthickness=1)
        file_row.pack(fill="x")
        file_row.columnconfigure(1, weight=1)
        file_icon = tk.Canvas(file_row, width=35, height=44, bg=INSET, bd=0, highlightthickness=0)
        file_icon.grid(row=0, column=0, padx=(10, 0))
        file_icon.create_rectangle(9, 11, 24, 32, outline="#95B56A", width=1.5)
        file_icon.create_line(13, 18, 21, 18, 13, 23, 21, 23, fill="#95B56A")
        self._label(file_row, textvariable=self.source_label, size=10,
                    background=INSET, width=1).grid(row=0, column=1, sticky="ew", padx=8)
        self.clear_source_button = self._button(file_row, "Clear", lambda:self.source.set(""), subtle=True, height=34)
        self.clear_source_button.grid(row=0, column=2, padx=6)
        source_row = tk.Frame(data, bg=SURFACE)
        source_row.pack(fill="x", pady=(11, 0))
        self._button(source_row, "Choose ISO", self._choose_iso).pack(side="left")
        self._button(source_row, "Choose maps folder", self._choose_maps).pack(side="left", padx=(8, 0))
        self.asset_label = self._label(data, textvariable=self.asset_status, size=9,
                                       color=MUTED, background=SURFACE, wraplength=630)
        self.asset_label.pack(anchor="w", pady=(9, 0))
        consent = self._card(body)
        self.data_consent = consent.master
        self.data_authorization = self._check(consent,
            "I am authorized to use my original Xbox game data with this mod.", self.authorized)
        self.data_authorization.pack(anchor="w")
        self.data_disclosure = self._label(consent,
            CONTENT_DISCLOSURE + "\nUse your own authorized Xbox data. Included Halo artwork: Microsoft.",
            9, color=MUTED, background=SURFACE, wraplength=630)
        self.data_disclosure.pack(anchor="w", pady=(2, 0))
        uninstall = self._card(body, "REMOVE NATIVE HALO VR")
        self.uninstall_card = uninstall.master
        self._label(uninstall,
            "Remove Halo VR and its Steam entry from the location selected on the next page.\n"
            "No disc image is needed. Your other games are kept.",
            10, background=SURFACE, wraplength=620).pack(anchor="w", pady=(0, 9))
        self._check(uninstall, "Keep my campaign saves in a backup (recommended)", self.keep_saves).pack(anchor="w")
        self._label(uninstall,
            "When checked, setup saves a backup on your Frame before removing the game.\n"
            "When unchecked, saves inside the game folder are removed with it.",
            9, color=MUTED, background=SURFACE, wraplength=620).pack(anchor="w", pady=(4, 0))
        self.uninstall_card.pack_forget()

    def _build_connection_page(self, body):
        instructions = self._card(body, "Prepare your Steam Frame")
        self._label(instructions,
            "1   Settings → System → Enable Developer Mode\n2   Developer → Set User Password",
            10, background=SURFACE).pack(anchor="w")
        self.connection_prepare_note = self._label(instructions,
            "Keep your computer and Frame on the same network.",
            9, color=MUTED, background=SURFACE, wraplength=620)
        self.connection_prepare_note.pack(anchor="w", pady=(7, 0))
        connection = self._card(body, "Connect securely")
        choices = tk.Frame(connection, bg=SURFACE)
        choices.pack(fill="x", pady=(0, 12))
        choices.columnconfigure((0, 1), weight=1, uniform="transports")
        self.transport_choices = []
        for index, title, subtitle, value in (
            (0, "Network", "Wi-Fi or Ethernet", "network"),
            (1, "USB-C cable", "Wired file transfer", "usb")):
            choice = Choice(choices, title, subtitle, self.transport, value, self._transport_changed)
            choice.grid(row=0, column=index, sticky="ew", padx=(0, 6) if index == 0 else (6, 0))
            self.transport_choices.append(choice)
        self.credentials_row = tk.Frame(connection, bg=SURFACE)
        self.credentials_row.pack(fill="x")
        self.network_panel = tk.Frame(self.credentials_row, bg=SURFACE)
        self._label(self.network_panel, "Frame address", 9, color=MUTED,
                    background=SURFACE).pack(anchor="w", pady=(0, 6))
        self._entry(self.network_panel, textvariable=self.host, width=22).pack(fill="x")
        self.usb_panel = tk.Frame(connection, bg=SURFACE)
        self._label(self.usb_panel,
            "USB tools are included. Connect a data-capable USB-C cable directly to the Frame.\n"
            "Approve this computer on the headset if a USB debugging prompt appears.",
            9, color=MUTED, background=SURFACE, wraplength=620).pack(anchor="w", pady=(0, 8))
        password_row = tk.Frame(self.credentials_row, bg=SURFACE)
        self.connection_password_row = password_row
        password_row.pack(side="left", fill="x", expand=True)
        self._label(password_row, "SSH password", 9, color=MUTED,
                    background=SURFACE).pack(anchor="w", pady=(0, 6))
        self._entry(password_row, textvariable=self.password, show="•", width=22).pack(fill="x")
        self.connection_label = self._label(connection, textvariable=self.connection_status, size=9,
                                           color=MUTED, background=SURFACE, wraplength=620)
        self.connection_label.pack(anchor="w", pady=(6, 0))
        connection_actions = tk.Frame(connection, bg=SURFACE)
        connection_actions.pack(fill="x", pady=(4, 0))
        self._button(connection_actions, "Test connection", self._test_connection).pack(side="left")
        self.advanced_button = self._button(connection_actions, "Advanced connection settings", self._toggle_advanced,
                                            subtle=True)
        self.advanced_button.pack(side="right")
        self.advanced_frame = tk.Frame(connection, bg=SURFACE)
        self.network_advanced = tk.Frame(self.advanced_frame, bg=SURFACE)
        self._label(self.network_advanced, "SSH port", 9, color=MUTED, background=SURFACE).pack(side="left")
        self._entry(self.network_advanced, textvariable=self.port, width=6).pack(side="left", padx=10)
        self._label(self.network_advanced, "Login: steamos", 9, color=MUTED, background=SURFACE).pack(side="left", padx=6)
        self.usb_advanced = tk.Frame(self.advanced_frame, bg=SURFACE)
        self._label(self.usb_advanced, "Optional alternative adb executable", 9,
                    color=MUTED, background=SURFACE).pack(anchor="w", pady=(0, 6))
        adb_row = tk.Frame(self.usb_advanced, bg=SURFACE)
        adb_row.pack(fill="x")
        self._entry(adb_row, textvariable=self.adb_path).pack(side="left", fill="x", expand=True)
        self._button(adb_row, "Browse adb.exe", self._choose_adb, subtle=True,
                     height=35).pack(side="right", padx=(8, 0))
        self._label(self.usb_advanced,
            "Leave blank to use available USB tools. You can select adb.exe from an extracted Platform Tools folder.",
            8, color=MUTED, background=SURFACE, wraplength=620).pack(anchor="w", pady=(5, 0))
        self._button(self.usb_advanced, "Download Google Platform Tools",
                     lambda:webbrowser.open(PLATFORM_TOOLS_URL), subtle=True,
                     height=33).pack(anchor="w", pady=(3, 8))
        self._label(self.usb_advanced, "USB device serial (optional)", 9,
                    color=MUTED, background=SURFACE).pack(anchor="w", pady=(0, 6))
        self._entry(self.usb_advanced, textvariable=self.usb_serial).pack(fill="x")
        self._label(self.usb_advanced, "Leave blank when only one Frame is connected. Login: steamos; SSH port: 22.",
                    8, color=MUTED, background=SURFACE, wraplength=620).pack(anchor="w", pady=(5, 0))
        self._transport_changed()
        acknowledgement = self._card(body)
        self._check(acknowledgement, "I have saved and closed games on my Frame.", self.steam_closed).pack(anchor="w")
        self.connection_steam_note = self._label(acknowledgement,
            "Steam Home and SteamVR stay running. Setup will show any manual library steps.",
            9, color=MUTED, background=SURFACE, wraplength=620)
        self.connection_steam_note.pack(anchor="w", pady=(2, 0))
        storage = self._card(body, "Install location")
        choices = tk.Frame(storage, bg=SURFACE)
        choices.pack(fill="x")
        choices.columnconfigure((0, 1), weight=1, uniform="storage")
        self.storage_choices = []
        for index, title, subtitle, value in (
            (0, "Internal storage", "Frame's built-in drive", "internal"),
            (1, "SD card", "Mounted on your Frame", "sd")):
            choice = Choice(choices, title, subtitle, self.storage_kind, value, self._storage_changed)
            choice.grid(row=0, column=index, sticky="ew", padx=(0, 6) if index == 0 else (6, 0))
            self.storage_choices.append(choice)
        self.storage_picker = ttk.Combobox(storage, textvariable=self.storage_label, state="disabled",
                                          style="Storage.TCombobox")
        self.storage_picker.pack(fill="x", pady=(10, 0))
        self.storage_picker.bind("<<ComboboxSelected>>", self._select_storage_card)
        self._label(storage, textvariable=self.storage_note, size=9, color=MUTED,
                    background=SURFACE, wraplength=620).pack(anchor="w", pady=(9, 0))
        self._button(storage, "Refresh storage", self._test_connection).pack(anchor="w", pady=(9, 0))
        self._label(storage,
            "Install uses your selected Xbox data. Repair and Uninstall affect only the selected location.\n"
            "Existing installations on another drive are kept; setup does not move them.",
            8, color=MUTED, background=SURFACE, wraplength=620).pack(anchor="w", pady=(8, 0))

    def _build_install_page(self, body):
        summary = self._card(body)
        self.install_summary = summary.master
        self._label(summary, textvariable=self.summary_heading, size=12, weight="bold",
                    background=SURFACE).pack(anchor="w", pady=(0, 8))
        for title, variable in ((self.summary_data_heading, self.summary_source), (None, self.summary_frame)):
            self._label(summary, text="STEAM FRAME" if title is None else None,
                        textvariable=title if title is not None else "",
                        size=8, weight="bold", color=MUTED, background=SURFACE).pack(anchor="w")
            self._label(summary, textvariable=variable, size=10, background=SURFACE,
                        wraplength=620).pack(anchor="w", pady=(4, 13))
        self._label(summary, textvariable=self.summary_action_heading, size=8, weight="bold",
                    color=MUTED, background=SURFACE).pack(anchor="w")
        self._label(summary, textvariable=self.summary_action, size=10,
                    background=SURFACE, wraplength=620).pack(anchor="w", pady=(4, 6))
        self._label(summary, textvariable=self.summary_note, size=9, color=MUTED,
                    background=SURFACE, wraplength=620).pack(anchor="w")
        self._label(summary, textvariable=self.summary_storage, size=9, color=MUTED,
                    background=SURFACE, wraplength=620).pack(anchor="w", pady=(9, 0))
        self.progress_card = self._card(body)
        progress_heading = tk.Frame(self.progress_card, bg=SURFACE)
        progress_heading.pack(fill="x")
        self.phase_label = self._label(progress_heading, textvariable=self.phase, size=11,
                                       weight="bold", background=SURFACE)
        self.phase_label.pack(side="left", fill="x", expand=True)
        self._label(progress_heading, textvariable=self.progress_label, size=11,
                    weight="bold", color=ACCENT, background=SURFACE).pack(side="right", padx=(8, 0))
        self.progress = ttk.Progressbar(self.progress_card, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=(14, 10))
        self._label(self.progress_card,
            "Approximate overall progress follows setup steps, not elapsed time.\n"
            "Downloads and build steps can hold the percentage; activity shows current work.",
            8, color=MUTED, background=SURFACE, wraplength=620).pack(anchor="w", pady=(0, 9))
        self.status_label = self._label(self.progress_card, textvariable=self.status, size=10,
                                        color=MUTED, background=SURFACE, wraplength=620)
        self.status_label.pack(anchor="w")
        self.retry_button = self._button(self.progress_card, "Add to Steam again", self._retry_steam)
        self.retry_button.pack(anchor="w", pady=(11, 0))
        self.retry_button.configure(state="disabled")
        self.retry_button.pack_forget()
        self.notes_button = self._button(self.progress_card, "View game description", self._show_steam_note)
        self.notes_button.pack_forget()
        self.install_note = self._label(body,
            "Allow 12 GiB free on the selected drive. The compiler container may also need temporary internal space.\nThe first native build can take a while.",
            9, color=MUTED, wraplength=620)
        self.install_note.pack(anchor="w", pady=(0, 10))

    def _apply_icon(self):
        try:
            from .install import resources_path
            directory = resources_path() / "ui"
            image_path = directory / "app-icon.png"
            if image_path.is_file():
                self._app_icon = tk.PhotoImage(file=str(image_path))
                self.iconphoto(True, self._app_icon)
            if sys.platform == "win32" and (directory / "app-icon.ico").is_file():
                self.iconbitmap(str(directory / "app-icon.ico"))
        except (OSError, tk.TclError):
            pass

    def _apply_window_theme(self, window=None):
        """Match the native Windows title bar to the dashboard's dark surface."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            window = window or self
            handle = ctypes.windll.user32.GetAncestor(window.winfo_id(), 2)
            enabled = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                handle, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
        except (AttributeError, OSError, tk.TclError):
            pass

    def _source_changed(self):
        self._asset_generation += 1
        if self._inspection_cancel is not None:
            self._inspection_cancel.set()
            self._inspection_cancel = None
            if self.busy and getattr(self, "operation", None) == "data":
                self._set_busy(False)
                self.status.set("Game data selection changed. Choose an original Xbox image or maps folder to continue.")
        source = self.source.get()
        self.source_label.set(Path(source).name if source else "No game data selected")
        if not source:
            self.asset_status.set(XBOX_REVISION_NOTE)
            self.music.load(None)
        self._update_summary()

    def _mode_changed(self):
        repair = self.mode.get() == "repair"
        uninstall = self.mode.get() == "uninstall"
        if uninstall:
            self.data_panel.pack_forget()
            self.data_consent.pack_forget()
        else:
            self.data_panel.pack(fill="x", pady=(0, 10))
            self.data_consent.pack(fill="x", pady=(0, 10))
        if uninstall:
            self.uninstall_card.pack(fill="x", pady=(0, 10))
        else:
            self.uninstall_card.pack_forget()
        self.data_title.configure(text="Replacement game data (optional)" if repair else "Your original Xbox game data")
        self.data_note.configure(text="Use valid installed Xbox maps, or choose data to replace them." if repair
                                  else "Choose a disc image or an extracted maps folder.")
        self.connection_steam_note.configure(text="Steam Home and SteamVR stay running. Uninstall may need a manual library step." if uninstall
                                            else "Steam Home and SteamVR stay running. Setup will show any manual library steps.")
        self.install_note.configure(text="Keep this window open until the uninstall finishes and setup disconnects." if uninstall
                                    else "Allow 12 GiB free on the selected drive. The compiler container may also need temporary internal space.\nThe first native build can take a while.")
        self._update_summary()
        self._update_navigation()
        if uninstall:
            self.retry_button.pack_forget()
            self.notes_button.pack_forget()
        self._show_page(self.current_page)

    def _update_summary(self):
        source = self.source.get()
        uninstall = self.mode.get() == "uninstall"
        self.summary_heading.set("UNINSTALL SUMMARY" if uninstall else "INSTALLATION SUMMARY")
        self.summary_data_heading.set("NATIVE GAME FOLDER" if uninstall else "GAME DATA")
        self.summary_source.set(self._storage_game_path() if uninstall else
                                Path(source).name if source else "Use valid Xbox maps already installed on the Frame")
        if self.transport.get() == "usb":
            serial = self.usb_serial.get().strip()
            self.summary_frame.set("USB-C cable" + (f" · {serial}" if serial else " · Detect connected Frame"))
        else:
            self.summary_frame.set(self.host.get().strip() or "Enter your Frame address")
        self.summary_action_heading.set("CAMPAIGN SAVES" if uninstall else "XBOX CONTROLS")
        self.summary_action.set(("Keep saves in a backup on the Frame" if self.keep_saves.get()
                                 else "Remove saves contained in the native game folder") if uninstall else
                                "A  Jump   ·   B  Melee   ·   X  Reload / use   ·   Y  Change weapon")
        self.summary_note.set("The native game files and its Steam entry will be removed." if uninstall else
                              "Motion aiming and Xbox-style controls are included. Steam artwork and game Notes are added automatically.")
        self.summary_storage.set("LOCATION: " + self._storage_game_path())

    def _storage_identity(self):
        return (self.transport.get(), self.host.get().strip(), self.port.get().strip(),
                self.usb_serial.get().strip(), self.adb_path.get().strip())

    def _invalidate_storage(self):
        self._storage_generation += 1
        self._storage_destinations = {}
        self._storage_picker_ids = {}
        self._storage_inventory_identity = None
        self.storage_label.set("")
        if hasattr(self, "storage_picker"):
            self.storage_picker.configure(values=())
            self._storage_changed()
        if self.busy and getattr(self, "operation", None) == "connection":
            self.cancel.set()
            self._set_busy(False)
        self._update_summary()

    def _storage_game_path(self):
        if self.storage_kind.get() == "internal":
            return self._storage_destinations.get("internal", {}).get("gamePath", "~/Games/HaloCENativeVR")
        destination = self._storage_destinations.get(self.storage_id.get())
        return destination["gamePath"] if destination else "Choose a mounted SD card on your Frame"

    def _storage_changed(self):
        if self.storage_kind.get() == "internal":
            self.storage_id.set("internal")
            self.storage_label.set("")
            selected = self._storage_destinations.get("internal")
            self.storage_note.set((f"Internal storage · {selected['freeBytes'] / 1024**3:.1f} GiB free\n" + selected["gamePath"]
                                   + ("\nAn existing installation was detected here." if selected.get("installed") else ""))
                                  if selected else "Internal storage is selected. SD cards are checked securely on your Frame.")
        else:
            cards = [item for item in self._storage_destinations.values() if item.get("kind") == "sd"]
            if self.storage_id.get() not in {item["id"] for item in cards}:
                self.storage_id.set(cards[0]["id"] if len(cards) == 1 else "")
            selected = self._storage_destinations.get(self.storage_id.get())
            self.storage_label.set(next((label for label, identifier in self._storage_picker_ids.items()
                                        if identifier == self.storage_id.get()), ""))
            if selected:
                self.storage_note.set(f"{selected['label']} · {selected['freeBytes'] / 1024**3:.1f} GiB free\n"
                                      + selected["gamePath"] + ("\nAn existing installation was detected here." if selected.get("installed") else
                                          "\nNo recognized installation is here. Use Install with your Xbox data."))
            elif cards:
                self.storage_note.set("Multiple SD cards are available. Choose the card to use; other installations are kept.")
            elif self._storage_inventory_identity == self._storage_identity():
                self.storage_note.set("No eligible mounted SD card was found. Insert or prepare a card in Steam Settings → Storage, then Refresh storage.")
            else:
                self.storage_note.set("Insert a card in your Frame and prepare it in Steam Settings → Storage, then Refresh storage.")
        if hasattr(self, "storage_picker"):
            self.storage_picker.configure(state="readonly" if not self.busy and self.storage_kind.get() == "sd"
                                          and self._storage_picker_ids else "disabled")
        self._update_summary()

    def _select_storage_card(self, event=None):
        self.storage_id.set(self._storage_picker_ids.get(self.storage_label.get(), ""))
        self._storage_changed()

    def _apply_storage_inventory(self, destinations, identity):
        self._storage_destinations = {item["id"]: dict(item) for item in destinations}
        self._storage_inventory_identity = identity
        self._storage_picker_ids = {}
        for index, item in enumerate(item for item in destinations if item.get("kind") == "sd"):
            label = f"{index + 1}. {item['label']} · {item['freeBytes'] / 1024**3:.1f} GiB free"
            if item.get("installed"):
                label += " · Installed"
            self._storage_picker_ids[label] = item["id"]
        self.storage_picker.configure(values=tuple(self._storage_picker_ids))
        self._storage_changed()

    def _show_page(self, index):
        if not 0 <= index < len(self.pages):
            return
        self.current_page = self.current_step = index
        self.max_page = max(self.max_page, index)
        self.pages[index].tkraise()
        self.canvas = self.pages[index].canvas
        self.step_count.set(f"SETUP / 0{index + 1} OF 03")
        uninstall = self.mode.get() == "uninstall"
        titles = ("UNINSTALL HALO VR" if uninstall else "GAME DATA", "CONNECT FRAME",
                  "UNINSTALL HALO VR" if uninstall else "INSTALL HALO VR")
        subtitles = ("Choose your save preference before removing the native game." if uninstall else
                     "Upgrades the native game; older checkpoints cannot load.\nCo-op uses one player per machine and matching builds.",
                     "Prepare SSH, then connect to your Steam Frame.",
                     "Review the native game and saves before removing them." if uninstall else
                     "Community VR mod. Xbox controls. Your Steam library.")
        self.page_title.configure(text=titles[index])
        self.page_subtitle.configure(text=subtitles[index])
        self._update_summary()
        self._update_navigation()
        if index == 2 and not self.installing:
            self.install_summary.pack(fill="x", pady=(0, 10), before=self.progress_card.master)

    _show_step = _show_page

    def _nav_to(self, index):
        if not self.busy and index <= self.max_page:
            self._show_page(index)

    def _back(self):
        if not self.busy and self.current_page > 0:
            self._show_page(self.current_page - 1)

    def _continue(self):
        if self.busy:
            return
        if self.current_page == 0:
            repair = self.mode.get() == "repair"
            if self.mode.get() != "uninstall" and (not self.authorized.get() or (not repair and not self.source.get())):
                messagebox.showinfo("Choose game data",
                    "Confirm that you are authorized to use the installed Xbox game data." if repair else
                    "Choose your original Xbox Halo CE image or maps, and confirm you are authorized to use them.", parent=self)
                return
            self._show_page(1)
        elif self.current_page == 1:
            try:
                settings = self._settings()
                settings.password = ""
            except ValueError as exc:
                messagebox.showerror("Connection details", str(exc), parent=self)
                return
            if not self.steam_closed.get():
                messagebox.showinfo("Close games first", GAME_CLOSE_NOTE, parent=self)
                return
            self.status.set("Setup removes the native game and its Steam entry, with your selected save preference." if self.mode.get() == "uninstall" else
                            "Setup builds the native game, applies Xbox controls, and automatically adds Steam artwork and game Notes.")
            self._show_page(2)
        else:
            if self.mode.get() == "uninstall":
                self._uninstall()
            else:
                self._install(repair=self.mode.get() == "repair")

    def _update_navigation(self):
        for index, nav in enumerate(self.nav_buttons):
            active = index == self.current_page
            nav.primary = active
            nav.subtle = not active
            nav.configure(state="disabled" if self.busy or index > self.max_page else "normal")
        self.back_button.configure(state="disabled" if self.busy or self.current_page == 0 else "normal")
        label = ("Continue" if self.current_page < 2 else "Uninstall Halo VR" if self.mode.get() == "uninstall"
                 else "Repair Halo VR" if self.mode.get() == "repair" else "Install Halo VR")
        self.next_button.configure(text=label, state="disabled" if self.busy else "normal")
        if self.busy:
            self.next_button.pack_forget()
            self.cancel_button.pack(side="right")
        else:
            self.cancel_button.pack_forget()
            self.next_button.pack(side="right")

    def _toggle_activity(self):
        self.activity_open = not self.activity_open
        if self.activity_open:
            self.activity_frame.grid()
        else:
            self.activity_frame.grid_remove()
        self.activity_button.configure(text="Hide activity" if self.activity_open else "Show activity")

    def _show_activity(self):
        if not self.activity_open:
            self._toggle_activity()

    def _display_progress(self):
        self.progress.configure(mode="determinate", value=self.progress_state.value)
        self.progress_label.set(f"{int(self.progress_state.value)}%")

    def _begin_setup_progress(self):
        self.uninstall_committing = False
        self.progress_state.reset()
        self._display_progress()
        # Keep the running phase and bar visible even at the minimum size.
        # The review summary has already served its purpose before installation.
        self.install_summary.pack_forget()
        self.retry_button.pack_forget()
        self.notes_button.pack_forget()
        self.pages[2].canvas.yview_moveto(0)
        self._show_activity()

    def _toggle_advanced(self):
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced_frame.pack(fill="x", pady=(9, 0))
        else:
            self.advanced_frame.pack_forget()
        self.advanced_button.configure(text="Hide connection settings" if self.advanced_open else "Advanced connection settings")

    def _transport_changed(self):
        self._invalidate_storage()
        usb = self.transport.get() == "usb"
        self.network_panel.pack_forget()
        self.usb_panel.pack_forget()
        if usb:
            self.usb_panel.pack(fill="x", before=self.credentials_row)
        else:
            self.network_panel.pack(side="left", fill="x", expand=True,
                                    padx=(0, 12), before=self.connection_password_row)
        self.network_advanced.pack_forget()
        self.usb_advanced.pack_forget()
        advanced = self.usb_advanced if usb else self.network_advanced
        advanced.pack(fill="x")
        self.connection_prepare_note.configure(text=(
            "Use a data-capable USB-C cable for transfer. The Frame still needs internet access for downloads and the native build."
            if usb else "Keep your computer and Frame on the same network. Wi-Fi and Ethernet both work."))
        self.connection_status.set("Your password stays in memory and is never saved.")
        self._update_summary()

    def _cancel_setup(self):
        if self.uninstall_committing:
            self.status.set("Finishing removal; please wait until setup disconnects.")
            return
        self.cancel.set()
        if self._inspection_cancel is not None:
            self._inspection_cancel.set()
        self.phase.set("Cancelling setup…")
        self.status.set("Keep this window open until setup stops. Check activity for the uninstall result." if getattr(self, "operation", None) == "uninstall"
                        else "Keep this window open until setup stops. Existing saves will be kept.")
        self.cancel_button.configure(state="disabled")

    def _dialog(self, title, subtitle):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(bg=BG)
        dialog.geometry("650x535")
        dialog.minsize(600, 480)
        dialog.transient(self)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        header = tk.Frame(dialog, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 16))
        self._label(header, title, 22, "bold").pack(anchor="w")
        self._label(header, subtitle, 10, color=MUTED).pack(anchor="w", pady=(6, 0))
        page = Page(dialog)
        page.grid(row=1, column=0, sticky="nsew", padx=28)
        footer = tk.Frame(dialog, bg=BG)
        footer.grid(row=2, column=0, sticky="ew", padx=28, pady=16)
        Button(footer, "Done", dialog.destroy, primary=True).pack(side="right")
        dialog.bind("<Escape>", lambda event:dialog.destroy())
        dialog.bind("<MouseWheel>", page.wheel)
        dialog.after_idle(lambda:self._apply_window_theme(dialog))
        return dialog, page.body

    def _show_controls(self):
        _, body = self._dialog("Xbox controls", "Familiar actions. Motion aiming stays enabled.")
        card = self._card(body)
        for controls, action in (("A / B", "Jump / accept  ·  Melee / back"),
                                 ("X / Y", "Reload / use  ·  Change weapon"),
                                 ("RT / LT", "Fire  ·  Throw grenade"),
                                 ("RB / LB", "Flashlight  ·  Change grenade"),
                                 ("Left stick", "Move  ·  Click to crouch"),
                                 ("Right stick", "Turn  ·  Click to zoom"),
                                 ("Menu / View", "Pause  ·  Scoreboard"),
                                 ("Both grips", "Hold to recenter")):
            row = tk.Frame(card, bg=SURFACE)
            row.pack(fill="x", pady=7)
            self._label(row, controls, 10, "bold", background=SURFACE, width=14).pack(side="left")
            self._label(row, action, 10, background=SURFACE).pack(side="left")
        self._label(body, "Hold the left grip near the foregrip for two-handed aiming.",
                    9, color=MUTED).pack(anchor="w", pady=(0, 8))

    def _show_steam_note(self):
        if self.busy or self.last_result is None:
            return
        notes = self.last_result.steam.get("notes", {})
        content = self._redact(notes.get("content", ""))
        if not content:
            return
        title = self._redact(notes.get("title", "Halo CE VR — About & controls"))
        _, body = self._dialog("Game description", "Add this description in Steam Notes for Halo.")
        card = self._card(body, "NOTE TITLE")
        title_entry = ttk.Entry(card)
        title_entry.insert(0, title)
        title_entry.configure(state="readonly")
        title_entry.pack(fill="x")
        card = self._card(body, "NOTE CONTENT")
        content_text = tk.Text(card, height=12, wrap="word", bg=INSET, fg=TEXT,
                              font=("Segoe UI", 10), relief="flat", padx=10, pady=10)
        content_text.insert("1.0", content)
        content_text.configure(state="disabled")
        content_text.pack(fill="both", expand=True)
        def copy_content():
            self.clipboard_clear()
            self.clipboard_append(content)
        Button(body, "Copy description", copy_content, primary=True).pack(anchor="w", pady=(0, 8))
        self._label(body, self._redact(notes.get("message", "")) or STEAM_NOTES_NOTE,
                    9, color=MUTED, wraplength=530).pack(anchor="w", pady=(0, 8))

    def _show_help(self):
        _, body = self._dialog("Help & sources", "Community VR mod installer requirements and sources.")
        disclosure = self._card(body, "COMMUNITY MOD INSTALLER")
        self._label(disclosure,
            "This installer builds the pinned Steam Frame VR port from public source using your authorized Xbox data.\n"
            + CONTENT_DISCLOSURE + "\n" + ARTWORK_CREDIT + " Full credits are in the project documentation.",
            10, background=SURFACE, wraplength=530).pack(anchor="w")
        card = self._card(body, "BEFORE YOU START")
        self._label(card,
            "• Use original Xbox Halo CE data you are authorized to use.\n"
            "• Original Xbox USA Rev 2 has been validated. Other retail revisions\n"
            "  are checked for a supported Xbox cache build:\n"
            "  NTSC: 01.10.12.2276 or 01.08.15.1749; PAL: 01.01.14.2342.\n"
            "• PC and Xbox 360 data are not supported.\n"
            "• Network: keep both devices on the same Wi-Fi or Ethernet network.\n"
            "• USB: use a data-capable USB-C cable with Developer Mode enabled.\n"
            "  USB tools are included. Approve USB debugging if prompted.\n"
            "• The Frame still needs internet access to download and build the game.\n"
            "• Save and close games. Steam Home and SteamVR stay running.\n"
            "• Install SteamVR and allow at least 12 GiB free on the selected drive.\n"
            "• For SD, prepare a writable ext4/f2fs card, then Refresh storage.\n"
            "• Repair refreshes the program and controls while preserving saves.\n"
            "• Install and repair automatically add Steam artwork and a game description in Steam Notes.\n"
            "• Online play uses the native port's own multiplayer protocol.\n\n" + EXPERIMENTAL_NOTICE,
            10, background=SURFACE, wraplength=530).pack(anchor="w")
        links = self._card(body, "Project references")
        Button(links, "Steam Frame SSH guide", lambda:webbrowser.open(SETUP_URL),
               subtle=True, background=SURFACE).pack(anchor="w")
        Button(links, "Google Android Platform Tools", lambda:webbrowser.open(PLATFORM_TOOLS_URL),
               subtle=True, background=SURFACE).pack(anchor="w")
        Button(links, "Native VR source", lambda:webbrowser.open(SOURCE_URL),
               subtle=True, background=SURFACE).pack(anchor="w")
        Button(links, "Installer project & documentation",
               lambda:webbrowser.open("https://github.com/ClassicWasTaken/HaloSteamFrameMod"),
               subtle=True, background=SURFACE).pack(anchor="w")

    def _redact(self, text):
        text = str(text)
        if self.password_to_redact:
            return text.replace(self.password_to_redact, "[redacted]")
        return text

    def _choose_iso(self):
        selected = filedialog.askopenfilename(title="Select your original Xbox Halo CE image", filetypes=[("Xbox disc image", "*.iso *.xiso"), ("All files", "*.*")])
        if selected:
            self._inspect(Path(selected))

    def _choose_maps(self):
        selected = filedialog.askdirectory(title="Select your original Xbox Halo CE maps folder")
        if selected:
            self._inspect(Path(selected))

    def _choose_adb(self):
        if self.busy:
            return
        selected = filedialog.askopenfilename(title="Select adb executable",
            filetypes=[("Android Debug Bridge", "adb.exe adb"), ("All files", "*.*")])
        if selected:
            self.adb_path.set(selected)

    def _inspect(self, selected):
        if self.busy and getattr(self, "operation", None) != "data":
            return
        selected = Path(selected)
        if self._inspection_cancel is not None:
            self._inspection_cancel.set()
        self._asset_generation += 1
        generation = self._asset_generation
        cancel = self._inspection_cancel = threading.Event()
        self.operation = "data"
        self.asset_status.set("Checking original Xbox game data…")
        self.status.set("Checking the selected Xbox game data…")
        self.music.load(None)
        self._set_busy(True)
        def worker():
            summary = error = None
            try:
                info = (inspect_maps(selected, cancel_event=cancel) if selected.is_dir()
                        else inspect_image(selected, cancel_event=cancel))
                summary = f"Validated {info.map_count} original Xbox maps • {info.estimated_bytes / 1e9:.2f} GB • {info.build}"
            except Exception as exc:
                error = str(exc)
            finally:
                # A single generation-bound result cannot clear the busy state
                # or report an error for a different, newer selection.
                self.events.put(("asset", generation, cancel, str(selected), summary, error))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_asset_check(self, generation, cancel, selected, summary, error):
        if generation != self._asset_generation or cancel is not self._inspection_cancel:
            return
        self._inspection_cancel = None
        self._set_busy(False)
        if cancel.is_set() or self.cancel.is_set():
            self.asset_status.set("Game data check cancelled. Choose an original Xbox image or maps folder to retry.")
            self.status.set("Game data check cancelled. Your previous selection was kept.")
            self.phase.set("Game data check cancelled")
            return
        if error is not None:
            self._show_setup_error(error)
            return
        self.source.set(selected)
        self.asset_status.set(summary)
        self.music.load(Path(selected))
        self.status.set("Game data validated. Connect your Frame next.")

    def _settings(self, *, storage_id=None):
        usb = self.transport.get() == "usb"
        if usb:
            host, port = "frame", 22
        else:
            try:
                port = int(self.port.get())
            except ValueError:
                raise ValueError("Enter a numeric SSH port.") from None
            host = self.host.get().strip()
        serial = self.usb_serial.get().strip() or None
        identity = f"usb:{serial}" if usb and serial else f"{host}:{port}" if not usb else None
        if storage_id is None:
            storage_id = self.storage_id.get()
            if self.storage_kind.get() == "sd" and (not storage_id or storage_id == "internal"
                    or self._storage_inventory_identity != self._storage_identity()
                    or storage_id not in self._storage_destinations):
                raise ValueError("Refresh storage and select a mounted SD card on your Frame before continuing.")
        return Settings(host=host, password=self.password.get(), port=port,
            transport=self.transport.get(), adb_path=self.adb_path.get().strip() or None,
            usb_serial=serial, known_host_fingerprints=dict(self.fingerprints),
            known_host_fingerprint=self.fingerprints.get(identity) if identity else None,
            accept_host_key=lambda h,a,v:self._approve_host(h,a,v,port),
            close_steam_for_shortcut=False, storage_id=storage_id)

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
        for check in self.checks:
            check.configure(state="disabled" if value else "normal")
        for choice in self.mode_choices:
            choice.configure(state="disabled" if value else "normal")
        for choice in self.transport_choices:
            choice.configure(state="disabled" if value else "normal")
        for choice in self.storage_choices:
            choice.configure(state="disabled" if value else "normal")
        self.storage_picker.configure(state="readonly" if not value and self.storage_kind.get() == "sd"
                                      and self._storage_picker_ids else "disabled")
        steam = self.last_result.steam if self.last_result is not None else {}
        pending_steam = (bool(self.last_result and self.last_result.requires_manual_steam_step)
                         or steam.get("artwork", {}).get("status") == "manual"
                         or steam.get("notes", {}).get("status") == "manual")
        allow_steam_retry = self.last_result is not None and pending_steam and self.mode.get() != "uninstall"
        self.retry_button.configure(state="normal" if not value and allow_steam_retry else "disabled")
        if allow_steam_retry:
            self.retry_button.pack(anchor="w", pady=(11, 0))
        else:
            self.retry_button.pack_forget()
        notes_pending = (allow_steam_retry and self.last_result.steam.get("notes", {}).get("status") == "manual"
                         and bool(self.last_result.steam.get("notes", {}).get("content")))
        self.notes_button.configure(state="normal" if not value and notes_pending else "disabled")
        if notes_pending:
            self.notes_button.pack(anchor="w", pady=(8, 0))
        else:
            self.notes_button.pack_forget()
        self.cancel_button.configure(state="normal" if value else "disabled")
        if value:
            self.cancel.clear()
        self._update_navigation()

    def _test_connection(self):
        if self.busy:
            return
        try:
            settings = self._settings(storage_id="internal")
        except ValueError as exc:
            messagebox.showerror("Connection details", str(exc), parent=self)
            return
        self.password_to_redact = settings.password
        self.operation = "connection"
        self._storage_generation += 1
        generation = self._storage_generation
        identity = self._storage_identity()
        self._storage_destinations = {}
        self._storage_picker_ids = {}
        self._storage_inventory_identity = None
        self.storage_picker.configure(values=())
        self._storage_changed()
        settings.accept_host_key = lambda h,a,v:self._approve_storage_host(generation, identity, h, a, v, settings.port)
        self._set_busy(True)
        self.status.set("Connecting to your Frame and checking storage…")
        self.connection_status.set("Connecting to your Frame and checking storage…")
        def worker():
            from .install import Installer
            try:
                result = Installer().discover_storage(settings, cancel_event=self.cancel)
                if result.cleanup_warning:
                    raise ValueError("Setup could not finish disconnecting after the connection check.\n" + result.cleanup_warning)
                self.events.put(("storage_result", generation, identity, settings.host_identity, result))
            except Exception as exc:
                cancelled = isinstance(exc, CancelledError) and not exc.requires_attention
                self.events.put(("storage_error", generation, identity, str(exc), cancelled))
            finally:
                settings.password = ""
                self.events.put(("storage_idle", generation, identity))
        threading.Thread(target=worker, daemon=True).start()

    def _approve_storage_host(self, generation, identity, host, algorithm, value, port):
        ready, answer = threading.Event(), []
        self.events.put(("storage_fingerprint", generation, identity, host, algorithm, value, port, ready, answer))
        while not ready.wait(0.1):
            if self.cancel.is_set() or generation != self._storage_generation:
                return False
        return bool(answer and answer[0])

    def _install(self, repair=False):
        if (not repair and not self.source.get()) or not self.authorized.get():
            messagebox.showinfo("Choose game data", "Confirm that you are authorized to use the installed Xbox game data." if repair else "Choose your original Xbox Halo CE image or maps, and confirm you are authorized to use them.", parent=self)
            return
        if not self.steam_closed.get():
            messagebox.showinfo("Close games first", GAME_CLOSE_NOTE, parent=self)
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
            if not messagebox.askyesno("Repair existing native game", "Setup will check " + self._storage_game_path() + " on your Frame and reinstall its native program files and Xbox controls. Saves and unrelated settings are preserved.\n\n" + data_note + "\n\nOnly this location is repaired; other installations are kept.\n\nRepair this installation?", parent=self):
                return
            settings.adopt_existing_native = True
        self.operation = "install"
        self.installing = True
        self._show_page(2)
        self._set_busy(True)
        self._begin_setup_progress()
        self.status.set("Preparing installation…")
        self.phase.set("Preparing your game")
        last_progress = [None, 0.0]
        def report(stage, message, percent=None):
            now = time.monotonic()
            if stage != "detail" and stage == last_progress[0] and now - last_progress[1] < 0.2 and percent != 100:
                return
            if stage != "detail":
                last_progress[:] = [stage, now]
            self.events.put(("progress", stage, str(message), percent))
        def worker():
            from .install import run
            try:
                if source is None:
                    result = run(settings, None, report, self.cancel)
                    self.events.put(("complete", result))
                    return
                info = (inspect_maps(source, cancel_event=self.cancel) if source.is_dir()
                        else inspect_image(source, cancel_event=self.cancel))
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
                cancelled = (isinstance(exc, ExtractionCancelled)
                             or isinstance(exc, CancelledError) and not exc.requires_attention)
                self.events.put(("error", str(exc), cancelled))
            finally:
                settings.password = ""
                self.events.put(("clear_password",))
                self.events.put(("idle",))
        threading.Thread(target=worker, daemon=True).start()

    def _retry_steam(self):
        if self.busy:
            return
        if not self.steam_closed.get():
            messagebox.showinfo("Close games first", GAME_CLOSE_NOTE, parent=self)
            return
        try:
            settings = self._settings(storage_id=getattr(self.last_result, "storage_id", "internal"))
            expected_frame = getattr(self.last_result, "host_fingerprint", None)
            if expected_frame:
                # A pending library update belongs to the Frame that installed
                # this game, even after its address or current selection changes.
                settings.known_host_fingerprint = expected_frame
                settings.accept_host_key = None
        except ValueError as exc:
            messagebox.showerror("Connection details", str(exc), parent=self)
            return
        self.password_to_redact = settings.password
        self.operation = "library"
        self.installing = True
        self._show_page(2)
        self._set_busy(True)
        self._begin_setup_progress()
        self.phase.set("Updating Halo's Steam info")
        self.status.set("Checking the installed game, artwork, and game notes…")
        def worker():
            from .install import Installer
            try:
                result = Installer().add_to_steam(settings,
                    lambda s,m,p=None:self.events.put(("progress",s,str(m),p)), self.cancel)
                self.events.put(("complete",result))
            except Exception as exc:
                self.events.put(("error",str(exc), isinstance(exc, CancelledError) and not exc.requires_attention))
            finally:
                settings.password = ""
                self.events.put(("clear_password",)); self.events.put(("idle",))
        threading.Thread(target=worker, daemon=True).start()

    def _uninstall(self):
        if self.busy:
            return
        if not self.steam_closed.get():
            messagebox.showinfo("Close games first", GAME_CLOSE_NOTE, parent=self)
            return
        try:
            settings = self._settings()
        except ValueError as exc:
            messagebox.showerror("Connection details", str(exc), parent=self)
            return
        keep_saves = self.keep_saves.get()
        saves_note = ("Your campaign saves will be backed up on the Frame before removing the game."
                      if keep_saves else "Campaign saves contained in the native game folder will also be removed.")
        confirmation = ("Remove the native Halo VR installation at " + self._storage_game_path() + " on your Frame?\n\n"
                        "This removes the native game program, Xbox maps, configuration files, and its native Halo Steam library entry.\n\n"
                        + saves_note + "\n\nOther games and saved backups are kept.\n\nOnce removal begins, let setup finish and disconnect.")
        if not messagebox.askyesno("Uninstall native Halo VR", confirmation, parent=self):
            settings.password = ""
            return
        self.password_to_redact = settings.password
        self.last_result = None
        self.operation = "uninstall"
        self.installing = True
        self._show_page(2)
        self._set_busy(True)
        self._begin_setup_progress()
        self.phase.set("Preparing to uninstall Halo VR")
        self.status.set("Checking the native game and Steam library before removal…")
        def worker():
            from .install import Installer
            try:
                result = Installer().uninstall(settings,
                    lambda s,m,p=None:self.events.put(("progress",s,str(m),p)),
                    self.cancel, keep_saves=keep_saves)
                self.events.put(("uninstall_complete", result))
            except Exception as exc:
                self.events.put(("error", str(exc), isinstance(exc, CancelledError) and not exc.requires_attention))
            finally:
                settings.password = ""
                self.events.put(("clear_password",))
                self.events.put(("idle",))
        threading.Thread(target=worker, daemon=True).start()

    def _append(self, text):
        text = self._redact(text)
        self.log_lines.append(text)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self):
        deadline = time.monotonic() + 0.015
        try:
            for _ in range(100):
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "storage_fingerprint":
                    _, generation, identity, host, algorithm, value, port, ready, answer = event
                    if generation != self._storage_generation or identity != self._storage_identity():
                        answer.append(False)
                        ready.set()
                        continue
                    kind = "fingerprint"
                    event = (kind, host, algorithm, value, port, ready, answer)
                if kind == "asset":
                    self._finish_asset_check(*event[1:])
                elif kind == "music":
                    self.music_status.set(self._redact(event[1]))
                elif kind == "fingerprint":
                    _, host, algorithm, value, port, ready, answer = event
                    accepted = messagebox.askyesno("Verify your Frame", f"First connection to {host}.\n\nSSH host key ({algorithm}):\n{value}\n\nCompare this with your Frame's host fingerprint on a trusted connection. Trust this device?", parent=self)
                    answer.append(accepted)
                    if accepted:
                        self._remember(host, port, value)
                    ready.set()
                elif kind in ("storage_result", "storage_error", "storage_idle"):
                    _, generation, identity, *payload = event
                    if generation != self._storage_generation or identity != self._storage_identity():
                        continue
                    if kind == "storage_result":
                        resolved, result = payload
                        if result.host_fingerprint:
                            self._remember(resolved, None, result.host_fingerprint)
                        self._apply_storage_inventory(result.destinations, identity)
                        self.status.set("Connected to your Frame. Review the install location before continuing.")
                        self.connection_status.set("Connected to your Frame. Storage checked; setup disconnected securely.")
                        self._append("SSH connection verified and storage checked. No password was saved.")
                        for item in result.destinations:
                            self._append(f"Storage: {item['label']} · {item['freeBytes'] / 1024**3:.1f} GiB free · {item['gamePath']}")
                        for item in getattr(result, "unavailable", ()):
                            self._append("Storage unavailable: " + item["mountPath"] + " — " + item["reason"])
                    elif kind == "storage_error":
                        self._show_setup_error(payload[0], len(payload) > 1 and bool(payload[1]))
                        self.password.set("")
                        self.password_to_redact = ""
                    else:
                        self._set_busy(False)
                elif kind == "connected":
                    _, identity, value = event
                    if value:
                        self._remember(identity, None, value)
                    self.status.set("Connected to your Frame. Ready to install.")
                    self.connection_status.set("Connected to your Frame. You're ready to continue.")
                    self._append("SSH connection verified. No password was saved.")
                elif kind == "progress":
                    _, stage, message, percent = event
                    detail = stage == "detail"
                    if stage == "uninstall" and getattr(self, "operation", None) == "uninstall":
                        self.uninstall_committing = True
                        self.cancel_button.configure(state="disabled")
                    if detail:
                        self._append(message)
                    else:
                        # The raw stage drives the phase table and activity choice;
                        # redaction applies to displayed text only, so a password
                        # that appears inside a phase name cannot stall the bar.
                        # _append redacts once on its own.
                        if not self.cancel.is_set() or self.uninstall_committing:
                            self.progress_state.update(stage, percent)
                            self._display_progress()
                            # Unknown phases fall back to the raw stage name, so the
                            # caption is redacted too, like every other display text.
                            self.phase.set(self._redact(self.progress_state.caption(stage)))
                            self.status.set(self._redact(message)[:500])
                        if self.installing or stage in ("build", "dependencies", "toolchain", "configure", "sdl", "compile", "build-check"):
                            self._show_activity()
                        self._append(f"{stage}: {message}")
                elif kind == "complete":
                    result = event[1]
                    self.last_result = result
                    cleanup_warning = self._redact(getattr(result, "cleanup_warning", None) or "")
                    cleanup_pending = bool(cleanup_warning)
                    library_update = getattr(self, "operation", None) == "library"
                    action = "repaired" if getattr(result, "repaired", False) else "installed"
                    game_name = result.steam.get("name", "Halo: Combat Evolved VR (Native)")
                    done = ("Halo's Steam library info has been updated. Your native game and saves were kept." if library_update else
                            f"Native Halo VR is {action}. Open Steam and launch {game_name}.")
                    if getattr(result, "backup_path", None):
                        self._append("Program-file backup: " + result.backup_path)
                    if result.requires_manual_steam_step:
                        done = ("Halo's Steam entry needs one more step. Your native game was kept.\n" if library_update else
                                "Native Halo VR is installed; its Steam entry needs one more step.\n")
                        done += result.steam.get("reason", "") + "\n" + result.steam.get("instructions", STEAM_ADD_NOTE)
                        self._append("Executable: " + result.game_path + "/halo")
                        self._append("Launch options: " + result.steam.get("launchOptions", "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0 %command%"))
                    artwork = result.steam.get("artwork", {})
                    artwork_pending = artwork.get("status") == "manual"
                    icon = artwork.get("icon", {})
                    # The shortcut icon is cosmetic. Keep its actual result in
                    # activity without making a successful game operation pending.
                    if icon:
                        self._append("Steam shortcut icon (optional): " + str(icon.get("status", "unknown")))
                        if icon.get("reason"):
                            self._append("Steam shortcut icon details: " + icon["reason"])
                        if icon.get("instructions"):
                            self._append("Steam shortcut icon instructions: " + icon["instructions"])
                        elif icon.get("status") == "manual":
                            self._append("Steam shortcut icon instructions: Click Add to Steam again to retry the library icon.")
                    notes = result.steam.get("notes", {})
                    if notes:
                        # The copyable fallback remains safe after the worker clears
                        # its password and the display-redaction token.
                        notes = {key: self._redact(value) if isinstance(value, str) else value
                                 for key, value in notes.items()}
                        result.steam["notes"] = notes
                    notes_pending = notes.get("status") == "manual"
                    info_pending = artwork_pending or notes_pending
                    if library_update and info_pending and not result.requires_manual_steam_step:
                        done = "Native Halo VR was kept; some Steam library info needs one more step. Your game and saves are unchanged."
                    self.progress_state.finish(pending=result.requires_manual_steam_step or info_pending or cleanup_pending)
                    self._display_progress()
                    if artwork_pending:
                        done += "\n\nHalo library art needs one more step.\n" + artwork.get("reason", "")
                        done += "\n" + artwork.get("instructions", STEAM_ART_NOTE)
                    if notes_pending:
                        done += "\n\nThe game description in Steam Notes needs one more step.\n"
                        done += notes.get("message", STEAM_NOTES_NOTE)
                        if notes.get("content"):
                            done += "\nClick View game description to copy the note."
                    elif notes.get("status") == "custom":
                        done += "\n\nYour existing custom game note was kept."
                    if cleanup_pending:
                        done += "\n\nThe game operation finished; connection cleanup needs attention.\n" + cleanup_warning
                    if info_pending or result.requires_manual_steam_step:
                        self.retry_button.pack(anchor="w", pady=(11, 0))
                    else:
                        self.retry_button.pack_forget()
                    done = self._redact(done)
                    self.phase.set("One more step in Steam" if result.requires_manual_steam_step
                                   else "Ready to play · Steam info pending" if info_pending
                                   else "Connection cleanup needs attention" if cleanup_pending
                                   else "Steam info updated" if library_update
                                   else "Complete")
                    self.status.set(done)
                    self._append(done)
                    extra = "" if library_update else "\n\nXbox controls and motion aiming are enabled. The native port uses its own multiplayer protocol; legacy PC servers and PC saves are incompatible."
                    messagebox.showinfo("Connection cleanup needs attention" if cleanup_pending
                                        else "Steam info updated" if library_update and not info_pending and not result.requires_manual_steam_step
                                        else "Steam info needs attention" if library_update else "Setup complete", done + extra, parent=self)
                elif kind == "uninstall_complete":
                    result = event[1]
                    self.last_result = None
                    self.last_uninstall_result = result
                    steam_pending = bool(getattr(result, "requires_manual_steam_step", False))
                    removal_pending = bool(getattr(result, "removal_pending", False))
                    remaining = tuple(getattr(result, "remaining_installs", ()))
                    cleanup_warning = self._redact(getattr(result, "cleanup_warning", None) or "")
                    pending = steam_pending or removal_pending or bool(remaining) or bool(cleanup_warning)
                    self.progress_state.finish(pending=pending)
                    self._display_progress()
                    if steam_pending:
                        done = "Uninstall needs one more step in Steam.\n" + result.steam.get("reason", "")
                        done += "\n" + result.steam.get("instructions", STEAM_REMOVE_NOTE)
                    elif removal_pending:
                        done = "Some files from an earlier uninstall were kept for manual review. Removal is not complete."
                    elif result.already_absent:
                        done = "Native Halo VR was already absent. Uninstall checks are complete."
                    else:
                        done = "Native Halo VR has been uninstalled from your Frame."
                    if remaining:
                        # Uninstall removes one selected storage destination; the
                        # others can only be removed after the user selects them.
                        done = ("Native Halo VR was not present on the selected storage, but it is still installed on another storage location of your Frame."
                                if result.already_absent else
                                "Native Halo VR has been uninstalled from the selected storage, but it is still installed on another storage location of your Frame.")
                        done += "\n" + "\n".join("Remaining install: " + path + " (storage " + identifier + ")"
                                                 for identifier, path in remaining)
                        done += "\nSelect that storage under Install location, then run Uninstall again to remove it."
                    if result.saved_backup_path:
                        done += "\n\nCampaign save backup: " + result.saved_backup_path
                    if getattr(result, "removal_warning", None):
                        done += "\n\n" + result.removal_warning
                    for backup in getattr(result, "recovered_save_backup_paths", ()):
                        done += "\nEarlier campaign save backup: " + backup
                    for retained in getattr(result, "retained_quarantine_paths", ()):
                        done += "\nPreserved uninstall folder: " + retained
                    if cleanup_warning:
                        done += "\n\nConnection cleanup needs attention.\n" + cleanup_warning
                    done = self._redact(done)
                    self.phase.set("Uninstall needs attention" if pending else "Halo VR uninstalled")
                    self.status.set(done)
                    self._append(done)
                    self.retry_button.pack_forget()
                    messagebox.showinfo("Uninstall needs attention" if pending else "Uninstall complete", done, parent=self)
                elif kind == "error":
                    self._show_setup_error(event[1], len(event) > 2 and bool(event[2]))
                elif kind == "clear_password":
                    self.password.set(""); self.password_to_redact = ""
                elif kind == "idle":
                    self._set_busy(False)
                    self.installing = False
                    self.uninstall_committing = False
                if time.monotonic() >= deadline:
                    break
        except queue.Empty:
            pass
        self.after(10 if not self.events.empty() else 80, self._drain)

    def _show_setup_error(self, text, cancelled=False):
        text = self._redact(text)
        if cancelled:
            # The worker tagged this outcome as a cancellation; report it as
            # stopped, never as a connection or data problem.
            summary = text.strip().splitlines()[0] if text.strip() else "Setup cancelled."
            if len(summary) > 500 or "\n" in text:
                summary = summary[:500] + "\n\nUse the setup activity panel (Show activity) for full details, or Save log for troubleshooting."
            self.status.set(summary)
            self.phase.set("Setup cancelled")
            if getattr(self, "operation", None) == "connection":
                self.connection_status.set("Connection check cancelled.")
            self._append(text)
            return
        remote_unverified = "may still be running" in text.lower()
        if "an installer build is still running" in text.lower():
            self.status.set("An earlier build is still running. Wake the Frame and finish or cancel that build first.")
            self.phase.set("Earlier build active")
        elif remote_unverified:
            self.status.set("Setup status is unverified. Wake the Frame and check setup activity before retrying.")
            self.phase.set("Connection needs attention")
        else:
            self.status.set("Setup stopped. See the message below; you can retry.")
            self.phase.set("Let's try that again")
        if getattr(self, "operation", None) == "connection":
            self.connection_status.set("Connection check needs attention. See setup activity, then retry.")
        elif getattr(self, "operation", None) == "data":
            self.asset_status.set("Couldn't validate this data. Choose an original Xbox image or maps folder.")
        self._append(text)
        summary = text.strip().splitlines()[0] if text.strip() else "Setup could not finish. You can retry."
        if len(summary) > 500 or "\n" in text:
            summary = summary[:500] + "\n\nUse the setup activity panel (Show activity) for full details, or Save log for troubleshooting."
        messagebox.showerror("Setup needs attention", summary, parent=self)

    def _remember(self, host, port, value):
        identity = host if port is None or host.startswith("usb:") else f"{host}:{port}"
        self.fingerprints[identity] = value
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
            if self.uninstall_committing:
                self.status.set("Finishing removal; please wait until setup disconnects.")
                return
            note = ("Cancel before removal begins? If removal has started, setup will finish it before disconnecting."
                    if getattr(self, "operation", None) == "uninstall" else
                    "Cancel the current setup? Existing games and saves will be kept.")
            if messagebox.askyesno("Cancel setup?", note, parent=self):
                self._cancel_setup()
            return
        self.password.set("")
        self.destroy()

    def destroy(self):
        self._asset_generation += 1
        if self._inspection_cancel is not None:
            self._inspection_cancel.set()
        music = getattr(self, "music", None)
        if music is not None:
            music.close()
        super().destroy()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-report":
        from .install import resources_path
        from .selftest import smoke_test
        report = smoke_test(resources_path())
        Path(sys.argv[2]).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return
    App().mainloop()
