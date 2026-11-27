"""CalmComposer v2 - a free MIDI idea generator for calm piano,
piano + nature and relaxing lofi.

6 tracks, sections A-F, clickable chords, live preview (Windows built-in
synth) and MIDI export for your DAW.
"""
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine

BG = "#1b1e2b"
BG2 = "#1f2333"
PANEL = "#242838"
FIELD = "#30354b"
FG = "#d6dbe8"
MUTED = "#6b7390"
GRID = "#2f3449"
SEL = "#4a6fa5"
COLORS = ["#8ab4f8", "#f4a8c0", "#9ece6a", "#bb9af7", "#7dcfff", "#e0af68"]
DIM = "#4a5068"

RULER = 22
LANE = 62
CHORD_H = 34
LEFT_W = 410
DRUM_ROWS = [42, 38, 36]   # hat (top), snare, kick (bottom)


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
        root.geometry("1240x760")
        root.minsize(1100, 700)
        root.configure(bg=BG)

        self.midi = WinMidi()
        self.tracks = [engine.TrackCfg() for _ in range(engine.NUM_TRACKS)]
        self.sections = [None] * 6
        self.cur = 0
        self.stop_evt = threading.Event()
        self.thread = None
        self.t0 = 0.0
        self.play_idx = []
        self.play_ranges = []

        self._style()
        self._vars()
        self._build()
        self.apply_preset()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tick()

    # ---- look ------------------------------------------------------------------
    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=PANEL, foreground=FG, fieldbackground=FIELD)
        s.configure("TLabel", background=PANEL, foreground=FG)
        s.configure("TFrame", background=PANEL)
        s.configure("TCheckbutton", background=PANEL, foreground=FG)
        s.map("TCheckbutton", background=[("active", PANEL)])
        s.configure("TButton", padding=5, background=FIELD, foreground=FG)
        s.map("TButton", background=[("active", SEL)])
        s.configure("Go.TButton", font=("Segoe UI", 14, "bold"), padding=12,
                    background="#3b7a57", foreground="#ffffff")
        s.map("Go.TButton", background=[("active", "#4a9b6e")])
        s.configure("Small.TButton", padding=1)
        s.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                    arrowcolor=FG, selectbackground=FIELD, selectforeground=FG)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)])
        s.configure("TSpinbox", fieldbackground=FIELD, foreground=FG, arrowcolor=FG)
        s.configure("TEntry", fieldbackground=FIELD, foreground=FG)
        s.configure("Horizontal.TScale", background=PANEL, troughcolor=FIELD)
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", SEL)

    def _vars(self):
        self.preset = tk.StringVar(value="Calm Piano")
        self.key = tk.StringVar(value="C")
        self.scale = tk.StringVar(value="Major")
        self.bpm = tk.IntVar(value=68)
        self.bars = tk.IntVar(value=8)
        self.bpb = tk.IntVar(value=4)
        self.npb = tk.IntVar(value=2)
        self.ext = tk.StringVar(value="Triads")
        self.cx = tk.DoubleVar(value=0.3)
        self.pop = tk.DoubleVar(value=0.35)
        self.swing = tk.DoubleVar(value=0.0)
        self.human = tk.DoubleVar(value=0.4)
        self.seed = tk.StringVar(value="1")
        self.lock = tk.BooleanVar(value=False)
        self.loop = tk.BooleanVar(value=True)
        self.song_mode = tk.BooleanVar(value=False)
        self.sec_var = tk.IntVar(value=0)
        self.tv = []
        for _ in range(engine.NUM_TRACKS):
            self.tv.append(dict(
                mode=tk.StringVar(value="Melody"), inst=tk.StringVar(value="Acoustic Piano"),
                oct=tk.IntVar(value=4), vol=tk.IntVar(value=100),
                mute=tk.BooleanVar(value=False), solo=tk.BooleanVar(value=False)))

    # ---- layout ----------------------------------------------------------------
    def _build(self):
        root = self.root

        # top bar
        top = ttk.Frame(root, padding=(10, 8))
        top.pack(side="top", fill="x")
        ttk.Label(top, text="Preset").pack(side="left")
        pc = ttk.Combobox(top, textvariable=self.preset, values=list(engine.PRESETS),
                          state="readonly", width=16)
        pc.pack(side="left", padx=(6, 16))
        pc.bind("<<ComboboxSelected>>", lambda e: self.apply_preset())
        ttk.Label(top, text="Section").pack(side="left", padx=(0, 6))
        for i, letter in enumerate("ABCDEF"):
            tk.Radiobutton(top, text=letter, variable=self.sec_var, value=i, indicatoron=False,
                           width=3, command=self.on_section, bg=FIELD, fg=FG, selectcolor=SEL,
                           activebackground=SEL, activeforeground=FG, relief="flat",
                           highlightthickness=0).pack(side="left", padx=1)
        ttk.Checkbutton(top, text="Song mode (play A to F)", variable=self.song_mode).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(top, text="Loop", variable=self.loop).pack(side="left", padx=(10, 0))
        ttk.Button(top, text="Play / Stop", command=self.toggle_play).pack(side="left", padx=(16, 4))
        ttk.Button(top, text="Export section", command=lambda: self.export(False)).pack(side="left", padx=4)
        ttk.Button(top, text="Export song", command=lambda: self.export(True)).pack(side="left", padx=4)
        self.status = tk.Label(top, text="", bg=PANEL, fg=MUTED, anchor="e")
        self.status.pack(side="right", fill="x", expand=True)

        # bottom panel (packed before the middle so it is never cut off)
        bot = ttk.Frame(root, padding=10)
        bot.pack(side="bottom", fill="x")
        ctl = ttk.Frame(bot)
        ctl.pack(side="left", fill="x", expand=True)
        btns = ttk.Frame(bot)
        btns.pack(side="right", padx=(10, 0))

        def fld(parent, label, make):
            f = ttk.Frame(parent)
            ttk.Label(f, text=label).pack(anchor="w")
            w = make(f)
            w.pack(fill="x")
            f.pack(side="left", padx=6)
            return w

        def combo(var, values, width, handler):
            def make(f):
                c = ttk.Combobox(f, textvariable=var, values=values, state="readonly", width=width)
                c.bind("<<ComboboxSelected>>", lambda e: handler())
                return c
            return make

        def slider(var):
            def make(f):
                sc = ttk.Scale(f, from_=0, to=1, variable=var, length=150)
                sc.bind("<ButtonRelease-1>", lambda e: self.regen_same())
                return sc
            return make

        r1 = ttk.Frame(ctl)
        r1.pack(anchor="w")
        fld(r1, "Key", combo(self.key, engine.NOTE_NAMES, 5, self.regen_same))
        fld(r1, "Scale", combo(self.scale, list(engine.SCALES), 16, self.regen_same))
        sp = fld(r1, "Tempo (BPM)", lambda f: ttk.Spinbox(f, from_=40, to=160, textvariable=self.bpm,
                                                         width=6, command=self.restart_if_playing))
        sp.bind("<Return>", lambda e: self.restart_if_playing())
        fld(r1, "Bars", combo(self.bars, [4, 8, 16, 32], 5, self.regen_same))
        fld(r1, "Beats per bar", combo(self.bpb, [3, 4, 5, 6], 5, self.regen_same))
        fld(r1, "Notes per beat", combo(self.npb, [1, 2, 3, 4], 5, self.regen_same))
        fld(r1, "Chords", combo(self.ext, ["Triads", "7th chords"], 10, self.regen_same))

        r2 = ttk.Frame(ctl)
        r2.pack(anchor="w", pady=(8, 0))
        fld(r2, "Complexity", slider(self.cx))
        fld(r2, "Population", slider(self.pop))
        fld(r2, "Swing", slider(self.swing))
        fld(r2, "Humanize", slider(self.human))

        def seed_box(f):
            box = ttk.Frame(f)
            ttk.Entry(box, textvariable=self.seed, width=9).pack(side="left")
            ttk.Checkbutton(box, text="Lock", variable=self.lock).pack(side="left", padx=4)
            return box
        fld(r2, "Seed", seed_box)

        ttk.Button(btns, text="GO", style="Go.TButton", command=self.go, width=14).pack(fill="x")
        ttk.Button(btns, text="Gen Chords", command=self.gen_chords).pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Gen Variation", command=self.gen_variation).pack(fill="x", pady=(4, 0))

        # middle: track rows (left) + lanes canvas (right)
        mid = tk.Frame(root, bg=BG)
        mid.pack(side="top", fill="both", expand=True)
        left = tk.Frame(mid, bg=PANEL, width=LEFT_W)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(left, bg=PANEL, height=RULER).pack(fill="x")
        for i in range(engine.NUM_TRACKS):
            self._track_row(left, i)
        cf = tk.Frame(left, bg=PANEL, height=CHORD_H)
        cf.pack(fill="x")
        cf.pack_propagate(False)
        tk.Label(cf, text="Chords  (click a chord to change it)", bg=PANEL, fg=MUTED).pack(anchor="w", padx=10, pady=8)

        self.canvas = tk.Canvas(mid, bg=BG, highlightthickness=0,
                                height=RULER + engine.NUM_TRACKS * LANE + CHORD_H)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_click)

        if not self.midi.ok:
            self.status.config(text="Preview: Windows only")

    def _track_row(self, parent, i):
        v = self.tv[i]
        row = tk.Frame(parent, bg=PANEL, height=LANE, highlightthickness=0)
        row.pack(fill="x")
        row.pack_propagate(False)
        line1 = tk.Frame(row, bg=PANEL)
        line1.pack(fill="x", padx=6, pady=(5, 0))
        tk.Label(line1, text=str(i + 1), bg=COLORS[i], fg="#10131c", width=2,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        mc = ttk.Combobox(line1, textvariable=v["mode"], values=engine.MODES, state="readonly", width=7)
        mc.pack(side="left")
        mc.bind("<<ComboboxSelected>>", lambda e, i=i: self.on_mode(i))
        ic = ttk.Combobox(line1, textvariable=v["inst"], values=list(engine.INSTRUMENTS),
                          state="readonly", width=14)
        ic.pack(side="left", padx=4)
        ic.bind("<<ComboboxSelected>>", lambda e, i=i: self.on_inst(i))
        ttk.Checkbutton(line1, text="M", variable=v["mute"], command=lambda i=i: self.on_mix(i)).pack(side="left")
        ttk.Checkbutton(line1, text="S", variable=v["solo"], command=lambda i=i: self.on_mix(i)).pack(side="left")
        ttk.Button(line1, text="New", width=4, style="Small.TButton",
                   command=lambda i=i: self.regen_one(i)).pack(side="left", padx=(4, 0))
        line2 = tk.Frame(row, bg=PANEL)
        line2.pack(fill="x", padx=6, pady=(3, 0))
        tk.Label(line2, text="Octave", bg=PANEL, fg=MUTED).pack(side="left", padx=(24, 4))
        sb = ttk.Spinbox(line2, from_=0, to=8, textvariable=v["oct"], width=3,
                         command=lambda i=i: self.on_oct(i))
        sb.pack(side="left")
        sb.bind("<Return>", lambda e, i=i: self.on_oct(i))
        tk.Label(line2, text="Volume", bg=PANEL, fg=MUTED).pack(side="left", padx=(14, 4))
        sc = ttk.Scale(line2, from_=0, to=127, variable=v["vol"], length=130,
                       command=lambda val, i=i: self.on_mix(i))
        sc.pack(side="left")

    # ---- settings <-> widgets ----------------------------------------------------
    def settings(self):
        def geti(var, default):
            try:
                return int(var.get())
            except (tk.TclError, ValueError):
                return default
        return engine.Settings(
            key=engine.NOTE_NAMES.index(self.key.get()), scale=self.scale.get(),
            bpm=max(40, min(160, geti(self.bpm, 68))), bars=geti(self.bars, 8),
            bpb=geti(self.bpb, 4), npb=geti(self.npb, 2),
            complexity=float(self.cx.get()), population=float(self.pop.get()),
            swing=float(self.swing.get()), humanize=float(self.human.get()),
            sevenths=self.ext.get() != "Triads")

    def sync_track(self, i):
        cfg, v = self.tracks[i], self.tv[i]
        cfg.mode = v["mode"].get()
        cfg.program = engine.INSTRUMENTS.get(v["inst"].get(), 0)
        try:
            cfg.octave = max(0, min(8, int(v["oct"].get())))
        except (tk.TclError, ValueError):
            pass
        cfg.vol = int(float(v["vol"].get()))
        cfg.mute = bool(v["mute"].get())
        cfg.solo = bool(v["solo"].get())

    def apply_preset(self):
        pr = engine.PRESETS[self.preset.get()]
        self.scale.set(pr["scale"])
        self.bpm.set(pr["bpm"])
        self.bars.set(pr["bars"])
        self.bpb.set(pr["bpb"])
        self.npb.set(pr["npb"])
        self.cx.set(pr["complexity"])
        self.pop.set(pr["population"])
        self.swing.set(pr["swing"])
        self.human.set(pr["humanize"])
        self.ext.set("7th chords" if pr["sevenths"] else "Triads")
        for i, (mode, prog, octv, muted) in enumerate(pr["tracks"]):
            v = self.tv[i]
            v["mode"].set(mode)
            v["inst"].set(engine.PROGRAM_NAME.get(prog, "Acoustic Piano"))
            v["oct"].set(octv)
            v["vol"].set(100)
            v["mute"].set(muted)
            v["solo"].set(False)
            self.sync_track(i)
            self.tracks[i].regen = 0
        self.sections = [None] * 6
        self.cur = 0
        self.sec_var.set(0)
        self.go()

    # ---- generation ---------------------------------------------------------------
    def current(self):
        return self.sections[self.cur]

    def go(self):
        was = self.is_playing()
        try:
            seed = int(self.seed.get())
        except ValueError:
            seed = None
        if seed is None or not self.lock.get():
            seed = random.randrange(1, 999999)
        self.seed.set(str(seed))
        for i in range(engine.NUM_TRACKS):
            self.sync_track(i)
        self.sections[self.cur] = engine.generate_section(self.settings(), self.tracks, seed)
        self.redraw()
        if was:
            self.play()

    def regen_same(self):
        sec = self.current()
        if sec is None:
            return self.go()
        for i in range(engine.NUM_TRACKS):
            self.sync_track(i)
        was = self.is_playing()
        self.sections[self.cur] = engine.generate_section(self.settings(), self.tracks, sec.seed)
        self.redraw()
        if was:
            self.play()

    def regen_one(self, i):
        sec = self.current()
        if sec is None:
            return
        self.sync_track(i)
        engine.regen_track(sec, self.settings(), self.tracks, i)
        self.redraw()
        self.restart_if_playing()

    def gen_chords(self):
        sec = self.current()
        if sec is None:
            return self.go()
        st = self.settings()
        degrees = engine.gen_degrees(st, random.Random(random.randrange(1 << 30)), sec.bars)
        engine.set_degrees(sec, st, self.tracks, degrees)
        self.redraw()
        self.restart_if_playing()

    def gen_variation(self):
        sec = self.current()
        if sec is None:
            return self.go()
        engine.vary(sec, self.settings(), self.tracks)
        self.redraw()
        self.restart_if_playing()

    def on_mode(self, i):
        self.sync_track(i)
        self.regen_one(i)

    def on_oct(self, i):
        self.sync_track(i)
        self.regen_one(i)

    def on_inst(self, i):
        self.sync_track(i)
        cfg = self.tracks[i]
        if cfg.mode != "Drums":
            self.midi.send(0xC0 | engine.channel_of(i, cfg), cfg.program, 0)

    def on_mix(self, i):
        self.sync_track(i)
        self.redraw()

    def on_section(self):
        self.cur = self.sec_var.get()
        if self.sections[self.cur] is None:
            self.go()
        else:
            self.seed.set(str(self.sections[self.cur].seed))
            self.redraw()
            if not self.song_mode.get():
                self.restart_if_playing()

    # ---- playback ---------------------------------------------------------------------
    def is_playing(self):
        return self.thread is not None and self.thread.is_alive()

    def toggle_play(self):
        if self.is_playing():
            self.stop()
        else:
            self.play()

    def restart_if_playing(self):
        if self.is_playing():
            self.play()

    def audible(self, i):
        return engine.audible(self.tracks)[i]

    def play(self):
        if not self.midi.ok:
            messagebox.showinfo("Preview", "Live preview works on Windows only.\nUse Export instead.")
            return
        st = self.settings()
        if self.song_mode.get():
            idx = [k for k, s in enumerate(self.sections) if s is not None]
        else:
            idx = [self.cur] if self.current() else []
        if not idx:
            return
        self.stop()
        secs = [self.sections[k] for k in idx]
        msgs = engine.to_messages(secs, st, self.tracks)
        spb = 60.0 / st.bpm
        ranges, acc = [], 0.0
        for k, s in zip(idx, secs):
            ranges.append((acc, acc + s.total_beats * spb, k))
            acc += s.total_beats * spb
        length = acc
        self.play_idx, self.play_ranges = idx, ranges
        self.stop_evt = stop = threading.Event()

        for i, cfg in enumerate(self.tracks):
            if cfg.mode != "Drums":
                self.midi.send(0xC0 | engine.channel_of(i, cfg), cfg.program, 0)

        def run():
            while not stop.is_set():
                self.t0 = time.perf_counter()
                for t, _, status, d1, d2, tr in msgs:
                    while not stop.is_set():
                        wait = t - (time.perf_counter() - self.t0)
                        if wait <= 0:
                            break
                        time.sleep(min(0.005, wait))
                    if stop.is_set():
                        break
                    if status & 0xF0 == 0x90:
                        if not self.audible(tr):
                            continue
                        d2 = engine.eff_vel(d2, self.tracks[tr])
                    self.midi.send(status, d1, d2)
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
        if self.is_playing() and self.play_ranges:
            total = self.play_ranges[-1][1]
            pos = (time.perf_counter() - self.t0) % total
            for a, b, k in self.play_ranges:
                if a <= pos < b:
                    if k != self.cur:
                        self.cur = k
                        self.sec_var.set(k)
                        self.seed.set(str(self.sections[k].seed))
                        self.redraw()
                    x = (pos - a) / (b - a) * c.winfo_width()
                    c.coords("ph", x, 0, x, c.winfo_height())
                    c.itemconfigure("ph", state="normal")
                    break
        else:
            c.itemconfigure("ph", state="hidden")
        self.root.after(30, self.tick)

    # ---- export ------------------------------------------------------------------------
    def export(self, whole_song):
        if whole_song:
            secs = [s for s in self.sections if s is not None]
        else:
            secs = [self.current()] if self.current() else []
        if not secs:
            return
        for i in range(engine.NUM_TRACKS):
            self.sync_track(i)
        name = "%s_%s_%s.mid" % (self.preset.get().replace(" + ", "_").replace(" ", "_"),
                                 self.key.get().replace("#", "s"),
                                 "song" if whole_song else "section%s" % "ABCDEF"[self.cur])
        path = filedialog.asksaveasfilename(defaultextension=".mid", initialfile=name,
                                            filetypes=[("MIDI file", "*.mid")])
        if not path:
            return
        with open(path, "wb") as f:
            f.write(engine.to_midi(secs, self.settings(), self.tracks))
        self.status.config(text="Saved: " + path)

    # ---- piano roll ------------------------------------------------------------------
    def lane_range(self, i, sec):
        cfg = self.tracks[i]
        notes = sec.notes[i]
        if notes:
            lo = min(n.pitch for n in notes) - 1
            hi = max(n.pitch for n in notes) + 1
        else:
            base = 12 * (cfg.octave + 1) + engine.NOTE_NAMES.index(self.key.get())
            lo, hi = base - 2, base + 14
        if hi - lo < 12:
            mid = (hi + lo) // 2
            lo, hi = mid - 6, mid + 6
        return lo, hi

    def redraw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        if w < 50:
            return
        sec = self.current()
        ok = engine.audible(self.tracks)
        for i in range(engine.NUM_TRACKS):
            y0 = RULER + i * LANE
            c.create_rectangle(0, y0, w, y0 + LANE - 1, fill=BG if i % 2 == 0 else BG2, outline="")
        if sec is None:
            c.create_line(0, 0, 0, 10, fill="#ffffff", tags="ph", state="hidden")
            return
        total = sec.total_beats
        height = RULER + engine.NUM_TRACKS * LANE + CHORD_H
        for beat in range(total + 1):
            x = beat / total * w
            bar = beat % sec.bpb == 0
            c.create_line(x, RULER if not bar else 0, x, height, fill=GRID if bar else "#262a3c")
            if bar and beat < total:
                c.create_text(x + 4, 4, text=str(beat // sec.bpb + 1), anchor="nw", fill=MUTED)
        for i, cfg in enumerate(self.tracks):
            y0 = RULER + i * LANE
            color = COLORS[i] if ok[i] else DIM
            if cfg.mode == "Drums":
                lane = (LANE - 6) / 3.0
                for n in sec.notes[i]:
                    x = n.start / total * w
                    row = DRUM_ROWS.index(n.pitch) if n.pitch in DRUM_ROWS else 1
                    ly = y0 + 3 + row * lane
                    c.create_rectangle(x, ly + 1, x + 4, ly + lane - 1, fill=color, outline="")
            else:
                lo, hi = self.lane_range(i, sec)
                rh = (LANE - 4) / float(hi - lo + 1)
                for n in sec.notes[i]:
                    x0 = n.start / total * w
                    x1 = (n.start + n.dur) / total * w
                    y = y0 + 2 + (hi - n.pitch) * rh
                    c.create_rectangle(x0, y, max(x1 - 1, x0 + 2), y + max(rh - 0.5, 2),
                                       fill=color, outline="")
        st = self.settings()
        top = RULER + engine.NUM_TRACKS * LANE
        for b, deg in enumerate(sec.degrees):
            x0 = b * sec.bpb / total * w
            x1 = (b + 1) * sec.bpb / total * w
            c.create_rectangle(x0 + 2, top + 3, x1 - 2, top + CHORD_H - 3, fill=FIELD, outline="")
            c.create_text((x0 + x1) / 2, top + CHORD_H / 2, text=engine.chord_name_for(st, deg),
                          fill=FG, font=("Segoe UI", 10, "bold"))
        c.create_line(0, 0, 0, height, fill="#ffffff", tags="ph", state="hidden")

    # ---- editing on the canvas -----------------------------------------------------------
    def on_click(self, e):
        sec = self.current()
        if sec is None:
            return
        w = max(1, self.canvas.winfo_width())
        top = RULER + engine.NUM_TRACKS * LANE
        if e.y >= top:
            bar = max(0, min(sec.bars - 1, int(e.x / w * sec.bars)))
            return self.chord_menu(bar, e)
        if e.y < RULER:
            return
        i = int((e.y - RULER) // LANE)
        if i >= engine.NUM_TRACKS:
            return
        cfg = self.tracks[i]
        beat = e.x / w * sec.total_beats
        step = 1.0 / sec.npb
        start = int(beat / step) * step
        y_in = e.y - RULER - i * LANE
        if cfg.mode == "Drums":
            row = max(0, min(2, int((y_in - 3) / ((LANE - 6) / 3.0))))
            pitch = DRUM_ROWS[row]
            for n in sec.notes[i]:
                if n.pitch == pitch and abs(n.start - start) < step / 2:
                    sec.notes[i].remove(n)
                    self.redraw()
                    return
            sec.notes[i].append(engine.Note(start, 0.1, pitch, 70))
        else:
            lo, hi = self.lane_range(i, sec)
            rh = (LANE - 4) / float(hi - lo + 1)
            pitch = max(lo, min(hi, hi - int((y_in - 2) / rh)))
            for n in sec.notes[i]:
                if n.pitch == pitch and n.start - 1e-6 <= beat < n.start + n.dur:
                    sec.notes[i].remove(n)
                    self.redraw()
                    return
            sec.notes[i].append(engine.Note(start, step, pitch, 70))
            self.preview(i, pitch)
        self.redraw()

    def preview(self, i, pitch):
        if not self.midi.ok:
            return
        cfg = self.tracks[i]
        ch = engine.channel_of(i, cfg)
        self.midi.send(0xC0 | ch, cfg.program, 0)
        self.midi.send(0x90 | ch, pitch, 80)
        self.root.after(300, lambda: self.midi.send(0x80 | ch, pitch, 0))

    def chord_menu(self, bar, e):
        st = self.settings()
        menu = tk.Menu(self.root, tearoff=0)
        for d in range(7):
            menu.add_command(label="%s   (%s)" % (engine.chord_name_for(st, d), engine.ROMAN[d]),
                             command=lambda d=d: self.set_degree(bar, d))
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def set_degree(self, bar, deg):
        sec = self.current()
        if sec is None:
            return
        degrees = list(sec.degrees)
        degrees[bar] = deg
        engine.set_degrees(sec, self.settings(), self.tracks, degrees)
        self.redraw()
        self.restart_if_playing()

    def on_close(self):
        self.stop()
        self.midi.close()
        self.root.destroy()


if __name__ == "__main__":
    tk_root = tk.Tk()
    App(tk_root)
    tk_root.mainloop()
