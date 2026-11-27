"""CalmComposer - generate calm piano, piano + nature and lofi MIDI ideas.

Press GO for a new idea, Play to hear it (Windows built-in synth), and
Export MIDI to open it in your DAW with a better piano.
"""
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine

BG = "#1b1e2b"
PANEL = "#242838"
FG = "#d6dbe8"
GRID = "#2f3449"
COLORS = {
    "Chords": "#8ab4f8", "Melody": "#f4a8c0", "Bass": "#9ece6a",
    "Pad": "#bb9af7", "Drums": "#e0af68",
}
STYLES = {"Arpeggio": "arp", "Soft pad": "pad", "Lofi stabs": "lofi"}
STYLE_LABEL = {v: k for k, v in STYLES.items()}


class WinMidi:
    """Tiny wrapper over the Windows built-in MIDI synth (winmm)."""

    def __init__(self):
        self.h = None
        self.ok = False
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            self.winmm = ctypes.windll.winmm
            self.winmm.midiOutOpen.argtypes = [
                ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
                ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint]
            self.winmm.midiOutShortMsg.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self.winmm.midiOutClose.argtypes = [ctypes.c_void_p]
            handle = ctypes.c_void_p()
            if self.winmm.midiOutOpen(ctypes.byref(handle), 0xFFFFFFFF, 0, 0, 0) == 0:
                self.h = handle
                self.ok = True
        except Exception:
            self.ok = False

    def send(self, status, d1, d2):
        if self.ok:
            self.winmm.midiOutShortMsg(self.h, status | (d1 << 8) | (d2 << 16))

    def silence(self):
        for ch in range(16):
            self.send(0xB0 | ch, 123, 0)
            self.send(0xB0 | ch, 120, 0)

    def close(self):
        if self.ok:
            self.silence()
            self.winmm.midiOutClose(self.h)
            self.ok = False


class App:
    def __init__(self, root):
        self.root = root
        root.title("CalmComposer")
        root.geometry("1040x660")
        root.configure(bg=BG)
        root.minsize(820, 560)

        self.midi = WinMidi()
        self.song = None
        self.stop_evt = threading.Event()
        self.thread = None
        self.t0 = 0.0

        self._style()
        self._build()
        self.apply_preset()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tick()

    # ---- UI ------------------------------------------------------------------
    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=PANEL, foreground=FG, fieldbackground="#30354b")
        s.configure("TLabel", background=PANEL, foreground=FG)
        s.configure("TCheckbutton", background=PANEL, foreground=FG)
        s.configure("TFrame", background=PANEL)
        s.configure("TButton", padding=6)
        s.configure("Go.TButton", font=("Segoe UI", 12, "bold"), padding=8)
        s.map("TCheckbutton", background=[("active", PANEL)])

    def _build(self):
        left = ttk.Frame(self.root, padding=12)
        left.pack(side="left", fill="y")
        right = tk.Frame(self.root, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self.preset = tk.StringVar(value="Calm Piano")
        self.key = tk.StringVar(value="C")
        self.scale = tk.StringVar(value="Major")
        self.bpm = tk.IntVar(value=68)
        self.bars = tk.IntVar(value=8)
        self.cx = tk.DoubleVar(value=0.3)
        self.swing = tk.DoubleVar(value=0.0)
        self.human = tk.DoubleVar(value=0.4)
        self.style = tk.StringVar(value="Arpeggio")
        self.seed = tk.StringVar(value="1")
        self.lock = tk.BooleanVar(value=False)
        self.loop = tk.BooleanVar(value=True)
        self.tv = {t: tk.BooleanVar(value=False) for t in engine.TRACKS}

        def row(label, widget):
            ttk.Label(left, text=label).pack(anchor="w", pady=(8, 0))
            widget.pack(fill="x")

        c = ttk.Combobox(left, textvariable=self.preset, values=list(engine.PRESETS), state="readonly")
        c.bind("<<ComboboxSelected>>", self.apply_preset)
        row("Style preset", c)
        row("Key", ttk.Combobox(left, textvariable=self.key, values=engine.NOTE_NAMES, state="readonly", width=6))
        row("Scale", ttk.Combobox(left, textvariable=self.scale, values=list(engine.SCALES), state="readonly"))
        row("Tempo (BPM)", ttk.Spinbox(left, from_=40, to=160, textvariable=self.bpm, width=6))
        row("Bars", ttk.Combobox(left, textvariable=self.bars, values=[4, 8, 16], state="readonly", width=6))
        row("Chord style", ttk.Combobox(left, textvariable=self.style, values=list(STYLES), state="readonly"))
        row("Complexity", ttk.Scale(left, from_=0, to=1, variable=self.cx))
        row("Swing", ttk.Scale(left, from_=0, to=1, variable=self.swing))
        row("Humanize", ttk.Scale(left, from_=0, to=1, variable=self.human))

        ttk.Label(left, text="Tracks").pack(anchor="w", pady=(10, 0))
        for t in engine.TRACKS:
            ttk.Checkbutton(left, text=t, variable=self.tv[t]).pack(anchor="w")

        sf = ttk.Frame(left)
        sf.pack(fill="x", pady=(10, 0))
        ttk.Label(sf, text="Seed").pack(side="left")
        ttk.Entry(sf, textvariable=self.seed, width=9).pack(side="left", padx=6)
        ttk.Checkbutton(sf, text="Lock", variable=self.lock).pack(side="left")
        ttk.Checkbutton(left, text="Loop playback", variable=self.loop).pack(anchor="w", pady=(6, 0))

        ttk.Button(left, text="GO  (new idea)", style="Go.TButton", command=self.go).pack(fill="x", pady=(14, 4))
        bf = ttk.Frame(left)
        bf.pack(fill="x")
        ttk.Button(bf, text="Play / Stop", command=self.toggle_play).pack(side="left", expand=True, fill="x")
        ttk.Button(bf, text="Export MIDI", command=self.export).pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.chords_lbl = tk.Label(right, text="", bg=BG, fg=FG, font=("Segoe UI", 13, "bold"),
                                   anchor="w", justify="left", wraplength=700)
        self.chords_lbl.pack(fill="x", padx=14, pady=(10, 0))
        self.canvas = tk.Canvas(right, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=8)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.status = tk.Label(right, text="", bg=BG, fg="#8a91a8", anchor="w", justify="left", wraplength=700)
        self.status.pack(fill="x", padx=14, pady=(0, 10))
        if not self.midi.ok:
            self.status.config(text="Live preview needs Windows. Use Export MIDI and open the file in your DAW.")

    # ---- generation --------------------------------------------------------------
    def apply_preset(self, *_):
        pr = engine.PRESETS[self.preset.get()]
        self.scale.set(pr["scale"])
        self.bpm.set(pr["bpm"])
        self.bars.set(pr["bars"])
        self.cx.set(pr["complexity"])
        self.swing.set(pr["swing"])
        self.human.set(pr["humanize"])
        self.style.set(STYLE_LABEL[pr["chord_style"]])
        for t in engine.TRACKS:
            self.tv[t].set(t in pr["tracks"])
        self.go()

    def params(self):
        try:
            bpm = max(40, min(160, int(self.bpm.get())))
        except (tk.TclError, ValueError):
            bpm = 68
        try:
            seed = int(self.seed.get())
        except ValueError:
            seed = random.randrange(1, 999999)
        return engine.Params(
            preset=self.preset.get(), key=engine.NOTE_NAMES.index(self.key.get()),
            scale=self.scale.get(), bpm=bpm, bars=int(self.bars.get()),
            complexity=float(self.cx.get()), swing=float(self.swing.get()),
            humanize=float(self.human.get()), seed=seed,
            chord_style=STYLES[self.style.get()],
            tracks=tuple(t for t in engine.TRACKS if self.tv[t].get()))

    def go(self):
        was_playing = self.is_playing()
        if not self.lock.get():
            self.seed.set(str(random.randrange(1, 999999)))
        self.song = engine.generate(self.params())
        self.chords_lbl.config(text="   ".join(self.song.chord_names))
        self.redraw()
        if was_playing:
            self.play()

    # ---- playback ----------------------------------------------------------------
    def is_playing(self):
        return self.thread is not None and self.thread.is_alive()

    def toggle_play(self):
        if self.is_playing():
            self.stop()
        else:
            self.play()

    def play(self):
        if not self.midi.ok:
            messagebox.showinfo("Preview", "Live preview works on Windows only.\nUse Export MIDI instead.")
            return
        if not self.song or not self.song.notes:
            return
        self.stop()
        msgs = engine.to_messages(self.song)
        length = self.song.length_sec
        self.stop_evt = stop = threading.Event()

        def run():
            while not stop.is_set():
                self.t0 = time.perf_counter()
                for t, st, d1, d2 in msgs:
                    while not stop.is_set():
                        wait = t - (time.perf_counter() - self.t0)
                        if wait <= 0:
                            break
                        time.sleep(min(0.005, wait))
                    if stop.is_set():
                        break
                    self.midi.send(st, d1, d2)
                while not stop.is_set() and time.perf_counter() - self.t0 < length:
                    time.sleep(0.005)
                if not self.loop.get():
                    break
            self.midi.silence()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        self.thread = None
        self.midi.silence()

    def tick(self):
        c = self.canvas
        if self.is_playing() and self.song:
            pos = ((time.perf_counter() - self.t0) % self.song.length_sec) / self.song.length_sec
            x = pos * c.winfo_width()
            c.coords("ph", x, 0, x, c.winfo_height())
            c.itemconfigure("ph", state="normal")
        else:
            c.itemconfigure("ph", state="hidden")
        self.root.after(30, self.tick)

    # ---- export ------------------------------------------------------------------
    def export(self):
        if not self.song:
            return
        name = "%s_%s_%s.mid" % (self.preset.get().replace(" + ", "_").replace(" ", "_"),
                                 self.key.get().replace("#", "s"), self.seed.get())
        path = filedialog.asksaveasfilename(defaultextension=".mid", initialfile=name,
                                            filetypes=[("MIDI file", "*.mid")])
        if not path:
            return
        with open(path, "wb") as f:
            f.write(engine.to_midi(self.song))
        self.status.config(text="Saved: " + path)

    # ---- piano roll --------------------------------------------------------------
    def redraw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if not self.song or w < 50 or h < 50:
            return
        total = self.song.total_beats
        notes = [n for n in self.song.notes if n.track != "Drums"]
        drums = [n for n in self.song.notes if n.track == "Drums"]
        top = 20
        drum_h = 66 if drums else 0
        roll_h = h - top - drum_h - (6 if drums else 0)
        lo = min((n.pitch for n in notes), default=48) - 1
        hi = max((n.pitch for n in notes), default=72) + 1
        if hi - lo < 24:
            mid = (hi + lo) // 2
            lo, hi = mid - 12, mid + 12
        rows = hi - lo + 1
        rh = roll_h / rows

        for beat in range(total + 1):
            x = beat / total * w
            bar = beat % 4 == 0
            c.create_line(x, top, x, h, fill=GRID if bar else "#262a3c")
            if bar and beat < total:
                c.create_text(x + 4, 4, text=str(beat // 4 + 1), anchor="nw", fill="#6b7390")
        for n in notes:
            x0 = n.start / total * w
            x1 = (n.start + n.dur) / total * w
            y0 = top + (hi - n.pitch) * rh
            c.create_rectangle(x0, y0, max(x1 - 1, x0 + 2), y0 + max(rh - 1, 2),
                               fill=COLORS[n.track], outline="")
        if drums:
            base = h - drum_h
            lane = drum_h / 3.0
            lanes = {36: 2, 38: 1, 37: 1, 42: 0, 46: 0}
            for n in drums:
                x = n.start / total * w
                ly = base + lanes.get(n.pitch, 0) * lane
                c.create_rectangle(x, ly + 3, x + 4, ly + lane - 3, fill=COLORS["Drums"], outline="")
        c.create_line(0, 0, 0, h, fill="#ffffff", tags="ph", state="hidden")

    def on_close(self):
        self.stop()
        self.midi.close()
        self.root.destroy()


if __name__ == "__main__":
    tk_root = tk.Tk()
    App(tk_root)
    tk_root.mainloop()
