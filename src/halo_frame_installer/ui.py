"""Locally drawn console-dashboard widgets, without additional dependencies."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont

BG = "#101612"
SIDEBAR = "#151D18"
SURFACE = "#202A24"
INSET = "#131C16"
TEXT = "#E4ECDA"
MUTED = "#A5B4A3"
BORDER = "#425440"
ACCENT = "#B8F548"
DISABLED = "#7A8975"
# Retain palette aliases for callers importing the small widget module.
WHITE = SURFACE
BLUE = ACCENT


def rounded(canvas, x1, y1, x2, y2, radius=12, **kwargs):
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [x1 + radius, y1, x2 - radius, y1, x2, y1,
              x2, y1 + radius, x2, y2 - radius, x2, y2,
              x2 - radius, y2, x1 + radius, y2, x1, y2,
              x1, y2 - radius, x1, y1 + radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


def chamfer(canvas, x1, y1, x2, y2, cut=10, **kwargs):
    """An angular inset panel, sized safely for its current canvas."""
    cut = min(cut, max(0, (x2 - x1) / 2), max(0, (y2 - y1) / 2))
    return canvas.create_polygon(
        x1 + cut, y1, x2 - cut, y1, x2, y1 + cut, x2, y2 - cut,
        x2 - cut, y2, x1 + cut, y2, x1, y2 - cut, x1, y1 + cut,
        **kwargs)


def power_orb(canvas, center_x, center_y, radius):
    """Original luminous-core drawing; it does not use console artwork."""
    for scale, fill, outline in (
        (1.0, "#0B100C", "#516644"), (.92, "#293A23", "#839A5C"),
        (.82, "#11200D", "#5F833A"), (.69, "#304D1C", "#739F36"),
        (.56, "#507B26", "#7DB332"), (.44, "#76A831", "#B5EA48"),
        (.30, "#9BCB3B", "#C6FA63"), (.14, "#C6F56B", "")):
        r = radius * scale
        canvas.create_oval(center_x - r, center_y - r, center_x + r,
                           center_y + r, fill=fill, outline=outline, width=1)
    r = radius * .82
    canvas.create_arc(center_x - r, center_y - r, center_x + r, center_y + r,
                      start=36, extent=107, style="arc", outline="#DAFC97", width=2)
    r = radius * .98
    canvas.create_arc(center_x - r, center_y - r, center_x + r, center_y + r,
                      start=217, extent=71, style="arc", outline="#759C40", width=2)
    for angle in (45, 135, 225, 315):
        a = math.radians(angle)
        canvas.create_line(center_x + math.cos(a) * radius * .99,
                           center_y + math.sin(a) * radius * .99,
                           center_x + math.cos(a) * radius * 1.16,
                           center_y + math.sin(a) * radius * 1.16,
                           fill="#637759", width=3)


class Button(tk.Canvas):
    """Beveled menu button with pointer, keyboard, focus and disabled states."""
    def __init__(self, parent, text, command, *, primary=False, subtle=False,
                 width=None, height=40, background=BG):
        self._text = text
        self._command = command
        self._state = "normal"
        self.primary = primary
        self.subtle = subtle
        self.hover = False
        self.focused = False
        self._font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._auto_width = width is None
        width = width or max(80, self._font.measure(text) + 36)
        height = max(height, self._font.metrics("linespace") + 14)
        super().__init__(parent, width=width, height=height, bg=background,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=True)
        self.bind("<Configure>", lambda event: self._draw())
        self.bind("<Enter>", lambda event: self._hover(True))
        self.bind("<Leave>", lambda event: self._hover(False))
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.bind("<FocusIn>", lambda event: self._focus(True))
        self.bind("<FocusOut>", lambda event: self._focus(False))
        self._draw()

    def _hover(self, value):
        self.hover = value
        self._draw()

    def _focus(self, value):
        self.focused = value
        self._draw()

    def _click(self, event=None):
        if self._state == "normal":
            self.focus_set()
            self._command()
        return "break"

    def _draw(self):
        self.delete("all")
        width = max(self.winfo_width(), int(super().cget("width")))
        height = max(self.winfo_height(), int(super().cget("height")))
        disabled = self._state == "disabled"
        if self.primary:
            fill = "#29372B" if disabled else "#426923" if self.hover else "#34541F"
            outline = "#51634C" if disabled else ACCENT
            foreground = DISABLED if disabled else "#E2FFAA"
            shine = "#657A4B" if disabled else "#A2CC62"
        else:
            fill = "#1B251E" if self.subtle else "#28352B"
            if self.hover and not disabled:
                fill = "#354C2A"
            outline = "#354637" if disabled else "#789058" if self.hover else BORDER
            foreground = DISABLED if disabled else ACCENT if self.subtle else TEXT
            shine = "#314133" if disabled else "#52664B"
        rounded(self, 3, 5, width - 3, height - 2, height / 2, fill="#080D09", outline="")
        rounded(self, 3, 3, width - 3, height - 5, height / 2,
                fill=fill, outline=outline, width=1)
        self.create_line(18, 6, width - 18, 6, fill=shine, width=1)
        self.create_line(20, height - 8, width - 20, height - 8,
                         fill="#192515", width=1)
        if self.focused and not disabled:
            rounded(self, 1, 1, width - 1, height - 1, height / 2,
                    fill="", outline=ACCENT, width=2)
        self.create_text(width / 2, height / 2 - 1, text=self._text, font=self._font, fill=foreground)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            if self._auto_width:
                kwargs["width"] = max(80, self._font.measure(self._text) + 36)
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            kwargs["cursor"] = "arrow" if self._state == "disabled" else "hand2"
            kwargs["takefocus"] = self._state != "disabled"
        result = super().configure(**kwargs)
        self._draw()
        return result

    config = configure

    def cget(self, key):
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        if key == "command":
            return self._command
        return super().cget(key)

    def invoke(self):
        if self._state == "normal":
            return self._command()


class Card(tk.Canvas):
    """Chamfered gunmetal enclosure with a green status rail."""
    def __init__(self, parent, *, padding=20, background=BG):
        super().__init__(parent, bg=background, bd=0, highlightthickness=0, height=80)
        self.padding = padding
        self.content = tk.Frame(self, bg=SURFACE)
        self.window = self.create_window(padding, padding, window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._resize_content)
        self.bind("<Configure>", self._resize)

    def _resize_content(self, event=None):
        height = self.content.winfo_reqheight() + self.padding * 2
        if int(self.cget("height")) != height:
            self.configure(height=height)

    def _resize(self, event):
        self.itemconfigure(self.window, width=max(1, event.width - self.padding * 2))
        self.delete("border")
        w, h = event.width, event.height
        chamfer(self, 2, 3, w - 2, h - 1, 12,
                fill="#080E09", outline="", tags="border")
        chamfer(self, 1, 1, w - 2, h - 3, 11,
                fill=SURFACE, outline=BORDER, width=1, tags="border")
        self.create_line(12, 2, w - 13, 2, fill="#657259", tags="border")
        self.create_line(17, 5, min(w - 20, 112), 5,
                         fill="#719F36", width=2, tags="border")
        self.create_line(12, h - 5, w - 13, h - 5,
                         fill="#122016", tags="border")
        # Static scanlines stay at panel edges, away from text and controls.
        for y in range(15, max(15, h - 14), 6):
            self.create_line(4, y, 9, y, fill="#2D3D2D", tags="border")
        self.tag_lower("border")


class Page(tk.Frame):
    """A page scrolls only when screen size or text scaling requires it."""
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                      relief="flat", bd=0, width=10,
                                      bg=BORDER, activebackground="#739449",
                                      troughcolor=INSET, highlightthickness=0)
        self.canvas.configure(yscrollcommand=self._scroll)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._body_changed)
        self.canvas.bind("<Configure>", self._canvas_changed)

    def _scroll(self, first, last):
        self.scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))

    def _body_changed(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_changed(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        self._body_changed()

    def wheel(self, event):
        if self.body.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 120), "units")


class Choice(tk.Canvas):
    def __init__(self, parent, title, subtitle, variable, value, command):
        super().__init__(parent, bg=SURFACE, bd=0, highlightthickness=0,
                         height=72, cursor="hand2", takefocus=True)
        self.title_text, self.subtitle = title, subtitle
        self.variable, self.value, self.command = variable, value, command
        self._state = "normal"
        self.focused = False
        self.bind("<Configure>", lambda event: self._draw())
        self.bind("<Button-1>", self._select)
        self.bind("<Return>", self._select)
        self.bind("<space>", self._select)
        self.bind("<FocusIn>", lambda event:self._focus(True))
        self.bind("<FocusOut>", lambda event:self._focus(False))
        variable.trace_add("write", lambda *args: self._draw())
        self._draw()

    def _focus(self, value):
        self.focused = value
        self._draw()

    def _select(self, event=None):
        if self._state == "normal":
            self.focus_set()
            self.variable.set(self.value)
            self.command()
        return "break"

    def _draw(self):
        self.delete("all")
        width = max(100, self.winfo_width())
        selected = self.variable.get() == self.value
        disabled = self._state == "disabled"
        line = "#536A40" if disabled else ACCENT if selected else BORDER
        chamfer(self, 1, 1, width - 1, 70, 8,
                fill="#2B4022" if selected else INSET,
                outline=line, width=1.5 if selected else 1)
        self.create_line(11, 3, width - 12, 3, fill="#70974E" if selected else "#425040")
        if self.focused and not disabled:
            chamfer(self, 4, 4, width - 4, 67, 6, fill="", outline=ACCENT, width=2)
        self.create_oval(17, 18, 31, 32, fill="#132011", outline=line, width=1.5)
        if selected:
            self.create_oval(21, 22, 27, 28, fill=DISABLED if disabled else ACCENT, outline="")
        self.create_text(43, 25, text=self.title_text, anchor="w",
                         font=("Segoe UI", 10, "bold"), fill=DISABLED if disabled else TEXT)
        self.create_text(18, 52, text=self.subtitle, anchor="w", font=("Segoe UI", 9),
                         fill=DISABLED if disabled else MUTED)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            kwargs["takefocus"] = self._state != "disabled"
            kwargs["cursor"] = "arrow" if self._state == "disabled" else "hand2"
        result = super().configure(**kwargs)
        self._draw()
        return result

    config = configure

    def cget(self, key):
        return self._state if key == "state" else super().cget(key)
