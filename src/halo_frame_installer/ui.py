"""Small, dependency-free desktop widgets for the installer."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

BG = "#F5F5F7"
SIDEBAR = "#ECEEF2"
WHITE = "#FFFFFF"
TEXT = "#1D1D1F"
MUTED = "#6E6E73"
BORDER = "#DEDFE3"
BLUE = "#007AFF"


def rounded(canvas, x1, y1, x2, y2, radius=12, **kwargs):
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [x1 + radius, y1, x2 - radius, y1, x2, y1,
              x2, y1 + radius, x2, y2 - radius, x2, y2,
              x2 - radius, y2, x1 + radius, y2, x1, y2,
              x1, y2 - radius, x1, y1 + radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class Button(tk.Canvas):
    """Rounded button with pointer, keyboard, focus and disabled states."""
    def __init__(self, parent, text, command, *, primary=False, subtle=False,
                 width=None, height=40, background=BG):
        self._text = text
        self._command = command
        self._state = "normal"
        self.primary = primary
        self.subtle = subtle
        self.hover = False
        self.focused = False
        self._font = tkfont.Font(family="Segoe UI", size=10,
                                weight="bold" if primary else "normal")
        self._auto_width = width is None
        width = width or max(80, self._font.measure(text) + 32)
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
            fill = "#B8CDE6" if disabled else "#0068DC" if self.hover else BLUE
            outline, foreground = fill, WHITE
        else:
            fill = super().cget("background") if self.subtle else WHITE
            if self.hover and not disabled:
                fill = "#E5EAF1" if self.subtle else "#F6F8FB"
            outline = fill if self.subtle else BORDER
            foreground = "#ADADB2" if disabled else BLUE if self.subtle else TEXT
        if self.focused and not disabled:
            rounded(self, 1, 1, width - 1, height - 1, 12, fill="", outline="#78B5FF", width=2)
        rounded(self, 3, 3, width - 3, height - 3, 10, fill=fill, outline=outline, width=1)
        self.create_text(width / 2, height / 2, text=self._text, font=self._font, fill=foreground)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            if self._auto_width:
                kwargs["width"] = max(80, self._font.measure(self._text) + 32)
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
    def __init__(self, parent, *, padding=20, background=BG):
        super().__init__(parent, bg=background, bd=0, highlightthickness=0, height=80)
        self.padding = padding
        self.content = tk.Frame(self, bg=WHITE)
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
        rounded(self, 1, 1, event.width - 1, event.height - 1, 16,
                fill=WHITE, outline=BORDER, width=1, tags="border")
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
                                      relief="flat", bd=0, width=10)
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
        super().__init__(parent, bg=WHITE, bd=0, highlightthickness=0,
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
        rounded(self, 1, 1, width - 1, 70, 12, fill="#F0F6FF" if selected else WHITE,
                outline=BLUE if selected else BORDER, width=1.5 if selected else 1)
        if self.focused and not disabled:
            rounded(self, 4, 4, width - 4, 67, 10, fill="", outline="#78B5FF", width=2)
        self.create_oval(17, 18, 31, 32, outline=BLUE if selected else "#B4B5BA", width=1.5)
        if selected:
            self.create_oval(21, 22, 27, 28, fill=BLUE, outline="")
        self.create_text(43, 25, text=self.title_text, anchor="w",
                         font=("Segoe UI", 10, "bold"), fill=MUTED if disabled else TEXT)
        self.create_text(18, 52, text=self.subtitle, anchor="w", font=("Segoe UI", 9), fill=MUTED)

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
