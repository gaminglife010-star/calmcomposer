"""CalmComposer engine v2: procedural MIDI generator for calm piano,
piano + nature and relaxing lofi.  Pure Python, no dependencies.

Model: Settings (global) + 6 TrackCfg (one per track) + Sections (A-F).
A Section holds its chord progression and the notes of every track.
"""
import math
import random
import re
import struct
from dataclasses import dataclass, field, replace

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]
# Chord names use flats where musicians expect them (Bb, Eb, Ab, Db).
CHORD_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

SCALES = {
    "Major": [0, 2, 4, 5, 7, 9, 11],
    "Minor": [0, 2, 3, 5, 7, 8, 10],
    "Dorian": [0, 2, 3, 5, 7, 9, 10],
    "Lydian": [0, 2, 4, 6, 7, 9, 11],
    "Pentatonic Major": [0, 2, 4, 7, 9],
    "Pentatonic Minor": [0, 3, 5, 7, 10],
}
PARENT = {"Pentatonic Major": "Major", "Pentatonic Minor": "Minor"}

_MAJOR = [[0, 5, 3, 4], [0, 4, 5, 3], [3, 4, 2, 5], [0, 2, 3, 4], [0, 3, 0, 4], [5, 3, 0, 4]]
_MINOR = [[0, 5, 2, 6], [0, 3, 6, 2], [0, 5, 3, 6], [0, 2, 5, 6], [0, 3, 4, 0], [5, 6, 0, 0]]
_DORIAN = [[0, 3, 0, 3], [0, 3, 6, 0], [0, 6, 3, 0], [0, 3, 2, 6]]
_LYDIAN = [[0, 1, 0, 1], [0, 1, 4, 0], [0, 4, 1, 0], [0, 1, 5, 0]]
PROGRESSIONS = {
    "Major": _MAJOR, "Pentatonic Major": _MAJOR,
    "Minor": _MINOR, "Pentatonic Minor": _MINOR,
    "Dorian": _DORIAN, "Lydian": _LYDIAN,
}

MODES = ["Melody", "Arp", "Chord", "Rhythm", "Pad", "Bass", "Drums"]

# General MIDI sounds that suit relaxing music (name -> 0-based program).
INSTRUMENTS = {
    "Acoustic Piano": 0, "Bright Piano": 1, "Electric Piano": 4, "Electric Piano 2": 5,
    "Celesta": 8, "Music Box": 10, "Vibraphone": 11, "Marimba": 12,
    "Nylon Guitar": 24, "Clean Guitar": 27, "Harp": 46, "Acoustic Bass": 32,
    "Finger Bass": 33, "Strings": 48, "Flute": 73, "New Age Pad": 88,
    "Warm Pad": 89, "Choir Pad": 91, "Halo Pad": 94,
}
PROGRAM_NAME = {v: k for k, v in INSTRUMENTS.items()}

PPQ = 480
NUM_TRACKS = 6

# tracks: (mode, program, octave, muted)
PRESETS = {
    "Calm Piano": dict(
        bpm=68, scale="Major", bars=8, bpb=4, npb=2, complexity=0.30, population=0.35,
        swing=0.0, humanize=0.4, sevenths=False,
        tracks=[("Melody", 0, 4, False), ("Arp", 0, 3, False), ("Bass", 32, 2, False),
                ("Pad", 89, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)]),
    "Piano + Nature": dict(
        bpm=56, scale="Major", bars=8, bpb=4, npb=2, complexity=0.15, population=0.20,
        swing=0.0, humanize=0.5, sevenths=False,
        tracks=[("Melody", 0, 4, False), ("Chord", 0, 3, False), ("Bass", 32, 2, True),
                ("Pad", 89, 4, False), ("Arp", 0, 3, True), ("Drums", 0, 3, True)]),
    "Relaxing Lofi": dict(
        bpm=78, scale="Minor", bars=8, bpb=4, npb=2, complexity=0.45, population=0.40,
        swing=0.5, humanize=0.6, sevenths=True,
        tracks=[("Melody", 0, 4, False), ("Rhythm", 4, 3, False), ("Bass", 33, 2, False),
                ("Pad", 89, 4, True), ("Chord", 4, 3, True), ("Drums", 0, 3, False)]),
    "Sleep Ambient": dict(
        bpm=50, scale="Lydian", bars=8, bpb=4, npb=2, complexity=0.10, population=0.12,
        swing=0.0, humanize=0.5, sevenths=False,
        tracks=[("Melody", 10, 5, False), ("Pad", 88, 4, False), ("Chord", 0, 3, False),
                ("Bass", 32, 2, True), ("Arp", 0, 3, True), ("Drums", 0, 3, True)]),
}


def _mood(bpm, scale, cx, pop, tracks, progs=None, swing=0.0, hum=0.5, sev=False):
    return dict(bpm=bpm, scale=scale, bars=8, bpb=4, npb=2, complexity=cx, population=pop,
                swing=swing, humanize=hum, sevenths=sev, progs=progs, mood=True, tracks=tracks)


# Moods: scale + tempo + chord progressions + instruments chosen for the feeling.
# Progressions are 0-based scale degrees (0 = I/i, 3 = IV/iv, 4 = V/v, 5 = vi/VI ...).
PRESETS.update({
    "Happy": _mood(100, "Major", 0.50, 0.55, [
        ("Melody", 1, 4, False), ("Arp", 12, 3, False), ("Bass", 33, 2, False),
        ("Pad", 48, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, False)],
        progs=[[0, 4, 5, 3], [0, 3, 4, 3], [0, 5, 3, 4], [3, 0, 4, 5]], swing=0.1, hum=0.4),
    "Sad": _mood(58, "Minor", 0.20, 0.20, [
        ("Melody", 0, 4, False), ("Chord", 0, 3, False), ("Bass", 32, 2, False),
        ("Pad", 48, 4, False), ("Arp", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 5, 2, 6], [0, 6, 5, 6], [0, 3, 5, 4], [5, 6, 0, 0]], hum=0.6),
    "Hopeful": _mood(84, "Major", 0.35, 0.40, [
        ("Melody", 0, 4, False), ("Arp", 0, 3, False), ("Bass", 33, 2, False),
        ("Pad", 48, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[5, 3, 0, 4], [0, 4, 5, 3], [3, 0, 4, 5], [0, 2, 3, 4]]),
    "Dreamy": _mood(62, "Lydian", 0.20, 0.25, [
        ("Melody", 8, 5, False), ("Arp", 46, 3, False), ("Bass", 32, 2, True),
        ("Pad", 89, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)], sev=True),
    "Peaceful": _mood(60, "Pentatonic Major", 0.12, 0.15, [
        ("Melody", 73, 4, False), ("Chord", 0, 3, False), ("Bass", 32, 2, True),
        ("Pad", 88, 4, False), ("Arp", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 3, 0, 4], [0, 5, 3, 0], [0, 4, 0, 3]]),
    "Melancholic": _mood(66, "Dorian", 0.30, 0.30, [
        ("Melody", 4, 4, False), ("Arp", 0, 3, False), ("Bass", 32, 2, False),
        ("Pad", 48, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)], sev=True),
    "Mysterious": _mood(70, "Pentatonic Minor", 0.30, 0.25, [
        ("Melody", 10, 5, False), ("Pad", 94, 4, False), ("Chord", 4, 3, False),
        ("Bass", 32, 2, False), ("Arp", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 5, 0, 6], [0, 2, 5, 2], [0, 6, 5, 6]], sev=True),
    "Romantic": _mood(72, "Major", 0.30, 0.35, [
        ("Melody", 0, 4, False), ("Arp", 46, 3, False), ("Bass", 32, 2, False),
        ("Pad", 48, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 5, 3, 4], [0, 2, 3, 4], [3, 4, 0, 5]], sev=True),
    "Nostalgic": _mood(76, "Major", 0.40, 0.40, [
        ("Melody", 11, 4, False), ("Rhythm", 5, 3, False), ("Bass", 33, 2, False),
        ("Pad", 89, 4, True), ("Chord", 0, 3, True), ("Drums", 0, 3, False)],
        progs=[[0, 5, 1, 4], [0, 2, 3, 3], [0, 5, 3, 4]], swing=0.3, sev=True),
    "Uplifting": _mood(96, "Major", 0.50, 0.55, [
        ("Melody", 1, 4, False), ("Arp", 12, 3, False), ("Bass", 33, 2, False),
        ("Pad", 48, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, False)],
        progs=[[0, 4, 5, 3], [5, 3, 0, 4], [0, 3, 4, 4]], swing=0.1, hum=0.4),
    "Rainy Day": _mood(72, "Minor", 0.35, 0.30, [
        ("Melody", 0, 4, False), ("Rhythm", 4, 3, False), ("Bass", 33, 2, False),
        ("Pad", 89, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, False)],
        progs=[[0, 5, 2, 6], [0, 3, 6, 2], [0, 5, 3, 6]], swing=0.4, sev=True),
})


def _plat(length, bpm, scale, cx, pop, tracks, progs=None, swing=0.0, hum=0.5, sev=False):
    d = _mood(bpm, scale, cx, pop, tracks, progs, swing, hum, sev)
    d.pop("mood")
    d["platform"] = True
    d["length"] = length      # suggested minutes: ~3 for Spotify singles, 30-60 for YouTube
    return d


# Platform presets: tuned for Spotify singles (about 3 min) and YouTube long videos.
PRESETS.update({
    "Sleep Music": _plat(60, 48, "Major", 0.08, 0.10, [
        ("Pad", 89, 4, False), ("Melody", 8, 5, False), ("Chord", 0, 3, False),
        ("Bass", 32, 2, False), ("Arp", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 3, 0, 4], [0, 5, 3, 4], [0, 4, 3, 0]]),
    "Study Lofi": _plat(30, 74, "Minor", 0.40, 0.38, [
        ("Melody", 0, 4, False), ("Rhythm", 4, 3, False), ("Bass", 33, 2, False),
        ("Pad", 89, 4, True), ("Chord", 0, 3, True), ("Drums", 0, 3, False)],
        swing=0.45, hum=0.6, sev=True),
    "Meditation": _plat(30, 54, "Pentatonic Major", 0.10, 0.12, [
        ("Melody", 73, 4, False), ("Pad", 88, 4, False), ("Chord", 46, 3, False),
        ("Bass", 32, 2, True), ("Arp", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 3, 0, 4], [0, 5, 0, 3]]),
    "Spa & Relax": _plat(30, 60, "Lydian", 0.20, 0.25, [
        ("Melody", 46, 4, False), ("Arp", 24, 3, False), ("Bass", 32, 2, False),
        ("Pad", 89, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)], sev=True),
    "Rainy Cafe": _plat(30, 80, "Minor", 0.40, 0.35, [
        ("Melody", 0, 4, False), ("Rhythm", 4, 3, False), ("Bass", 32, 2, False),
        ("Pad", 89, 4, True), ("Chord", 0, 3, True), ("Drums", 0, 3, False)],
        progs=[[0, 3, 6, 2], [0, 5, 3, 4], [0, 2, 5, 6]], swing=0.45, hum=0.6, sev=True),
    "Healing Piano": _plat(3, 64, "Major", 0.30, 0.30, [
        ("Melody", 0, 4, False), ("Arp", 0, 3, False), ("Bass", 32, 2, True),
        ("Pad", 48, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 4, 5, 3], [5, 3, 0, 4], [0, 5, 3, 4]]),
    "Morning Calm": _plat(3, 76, "Major", 0.35, 0.40, [
        ("Melody", 24, 4, False), ("Arp", 0, 3, False), ("Bass", 32, 2, False),
        ("Pad", 89, 4, False), ("Chord", 0, 3, True), ("Drums", 0, 3, True)],
        progs=[[0, 4, 5, 3], [0, 3, 4, 3], [5, 3, 0, 4]]),
    "Focus Ambient": _plat(60, 58, "Dorian", 0.10, 0.12, [
        ("Pad", 94, 4, False), ("Chord", 4, 3, False), ("Melody", 11, 4, False),
        ("Bass", 32, 2, False), ("Arp", 0, 3, True), ("Drums", 0, 3, True)], sev=True),
})


@dataclass
class Note:
    start: float   # beats
    dur: float     # beats
    pitch: int
    vel: int


@dataclass
class TrackCfg:
    mode: str = "Melody"
    program: int = 0
    octave: int = 4
    vol: int = 100
    mute: bool = False
    solo: bool = False
    regen: int = 0


@dataclass
class Settings:
    key: int = 0
    scale: str = "Major"
    bpm: int = 68
    bars: int = 8
    bpb: int = 4          # beats per bar
    npb: int = 2          # notes per beat (grid)
    complexity: float = 0.3
    population: float = 0.35
    swing: float = 0.0
    humanize: float = 0.4
    sevenths: bool = False
    progs: object = None   # optional list of progressions (a mood overrides the default)


@dataclass
class Section:
    bars: int
    bpb: int
    npb: int
    chords: list          # one Chord per bar, relative to the key
    notes: list = field(default_factory=list)   # one list[Note] per track
    seed: int = 1
    custom: bool = False  # True once the chords were typed / picked by hand
    var: int = 0          # accompaniment variation (chords, pad, bass, drums); the melody ignores it

    @property
    def total_beats(self):
        return self.bars * self.bpb


def scale_pitch(scale, idx, root):
    n = len(scale)
    return root + scale[idx % n] + 12 * (idx // n)


# Chord qualities as semitone intervals above the root.
QUALITIES = {
    "": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8),
    "sus2": (0, 2, 7), "sus4": (0, 5, 7), "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9),
    "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10),
    "m7b5": (0, 3, 6, 10), "dim7": (0, 3, 6, 9), "add9": (0, 4, 7, 14), "madd9": (0, 3, 7, 14),
}
_BY_INTERVALS = {v: k for k, v in QUALITIES.items()}
QUALITY_ALIASES = {
    "": "", "maj": "", "M": "", "major": "", "m": "m", "min": "m", "-": "m", "minor": "m",
    "dim": "dim", "o": "dim", "\u00b0": "dim", "aug": "aug", "+": "aug",
    "sus2": "sus2", "sus4": "sus4", "sus": "sus4", "6": "6", "m6": "m6", "min6": "m6",
    "7": "7", "dom7": "7", "maj7": "maj7", "M7": "maj7", "\u0394": "maj7", "\u03947": "maj7",
    "m7": "m7", "min7": "m7", "-7": "m7", "m7b5": "m7b5", "\u00f8": "m7b5", "\u00f87": "m7b5",
    "dim7": "dim7", "o7": "dim7", "add9": "add9", "madd9": "madd9", "m(add9)": "madd9",
}
_FLATS = {"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10, "Cb": 11, "Fb": 4, "E#": 5, "B#": 0}


@dataclass(frozen=True)
class Chord:
    root: int = 0   # semitones above the key (0-11), so chords follow the Key setting
    q: str = ""     # quality, a key of QUALITIES


def chord_label(st, chord):
    return CHORD_NAMES[(st.key + chord.root) % 12] + chord.q


def parse_chord(st, text):
    """'Am', 'F#m7', 'Bbmaj7', 'C/E' (slash ignored) -> Chord relative to the key, or None."""
    t = text.strip().split("/")[0]
    if not t or t[0].upper() not in "ABCDEFG":
        return None
    name = t[0].upper()
    rest = t[1:]
    if rest[:1] in ("#", "\u266f"):
        name += "#"
        rest = rest[1:]
    elif rest[:1] == "\u266d" or (rest[:1] == "b" and rest[1:2] not in ("5",) and name + "b" in _FLATS):
        name += "b"
        rest = rest[1:]
    if name in _FLATS:
        pc = _FLATS[name]
    elif name in NOTE_NAMES:
        pc = NOTE_NAMES.index(name)
    else:
        return None
    q = QUALITY_ALIASES.get(rest)
    if q is None:
        return None
    return Chord((pc - st.key) % 12, q)


def parse_progression(st, text):
    """Split on spaces, commas, bars and arrows; returns (chords, bad_tokens)."""
    tokens = [x for x in re.split(r"[\s,|>\u2192]+", text.replace("-->", " ").replace("->", " ")) if x]
    chords, bad = [], []
    for tok in tokens:
        c = parse_chord(st, tok)
        (chords if c else bad).append(c if c else tok)
    return chords, bad


def degree_chord(st, deg, sevenths):
    """Diatonic chord on a scale degree of the (parent) scale, as a Chord."""
    parent = SCALES[PARENT.get(st.scale, st.scale)]
    ks = (0, 2, 4, 6) if sevenths else (0, 2, 4)
    pcs = [scale_pitch(parent, deg + k, 0) for k in ks]
    q = _BY_INTERVALS.get(tuple(p - pcs[0] for p in pcs), "")
    return Chord(pcs[0] % 12, q)


def diatonic_chords(st):
    return [degree_chord(st, d, st.sevenths) for d in range(7)]


def nearest_degree(scale, root):
    """Index of the scale tone closest to a pitch class (used by the melody)."""
    best, best_d = 0, 99
    for i, p in enumerate(scale):
        d = min((p - root) % 12, (root - p) % 12)
        if d < best_d:
            best, best_d = i, d
    return best


def voicing(st, chord, base, triad_only=False, inv=0):
    r = base + chord.root
    iv = QUALITIES[chord.q]
    notes = [r + i for i in (iv[:3] if triad_only else iv)]
    for _ in range(inv):            # inversion: lift the lowest note an octave
        notes.append(notes.pop(0) + 12)
    while max(notes) > base + 24:
        notes = [n - 12 for n in notes]
    return notes


def chord_name_for(st, chord):
    return chord_label(st, chord)


def channel_of(i, cfg):
    return 9 if cfg.mode == "Drums" else i


def audible(tracks):
    solos = any(t.solo for t in tracks)
    return [(t.solo if solos else not t.mute) for t in tracks]


def eff_vel(vel, cfg):
    return max(1, min(127, int(vel * cfg.vol / 100.0)))


# ---- generation --------------------------------------------------------------------

def gen_chords(st, rng, bars):
    prog = rng.choice(st.progs or PROGRESSIONS[st.scale])
    degrees = [prog[i % len(prog)] for i in range(bars)]
    degrees[-1] = 0
    return [degree_chord(st, d, st.sevenths) for d in degrees]


def _track_rng(seed, i, cfg, var=0):
    v = 0 if cfg.mode in ("Melody", "Arp") else var
    return random.Random(seed * 131 + i * 17 + cfg.regen * 7919 + v * 104729)


def gen_track(st, cfg, degrees, rng, bpb, npb):
    bars = len(degrees)
    total = bars * bpb
    slots = bpb * npb
    step = 1.0 / npb
    cx = st.complexity
    pop = st.population
    base = 12 * (cfg.octave + 1) + st.key
    swing_on = npb in (2, 4)
    notes = []

    def tm(bar, slot):
        t = bar * bpb + slot * step
        if swing_on and slot % 2 == 1:
            t += st.swing * step * 0.66
        return t

    def beat_t(bar, beat):
        t = bar * bpb + beat
        if abs((beat % 1.0) - 0.5) < 1e-6:
            t += st.swing * 0.33
        return t

    def add(start, dur, pitch, vel, tight=False):
        h = st.humanize * (0.4 if tight else 1.0)
        s = max(0.0, start + rng.uniform(-1, 1) * 0.025 * h)
        d = min(dur, total - s)
        if d <= 0.02 or not 0 <= pitch <= 127:
            return
        v = max(1, min(127, int(vel + rng.uniform(-1, 1) * 10 * h)))
        notes.append(Note(s, d, int(pitch), v))

    def pick_slots(k, p0=0.8):
        s = set()
        if rng.random() < p0:
            s.add(0)
        k = max(1, min(k, slots))
        while len(s) < k:
            s.add(rng.randrange(slots))
        return sorted(s)

    def fold(p, lo=-5, hi=24):
        while p > base + hi:
            p -= 12
        while p < base + lo:
            p += 12
        return p

    prev = [None]

    def led_voicing(chord, triad_only=False):
        """Pick the inversion closest to the previous chord (smooth voice leading),
        with a little randomness so repeated sections are not identical."""
        n = 3 if triad_only else len(QUALITIES[chord.q])
        ref = prev[0] if prev[0] is not None else base + 8
        cands = []
        for inv in range(n):
            v = voicing(st, chord, base, triad_only, inv)
            cands.append((abs(sum(v) / float(len(v)) - ref), inv, v))
        cands.sort()
        pick = cands[0] if (len(cands) == 1 or rng.random() < 0.65) else cands[1]
        prev[0] = sum(pick[2]) / float(len(pick[2]))
        return pick[2]

    mode = cfg.mode

    if mode == "Melody":
        mel = SCALES[st.scale]
        strong = max(1, npb * 2)
        steps = [-1, 1]
        if cx > 0.25:
            steps += [-2, 2]
        if cx > 0.6:
            steps += [-3, 3, -4, 4]
        motif = []
        for mb in range(2):
            k = int(round(slots * (0.06 + 0.40 * pop) + rng.uniform(-1, 1)))
            sl = pick_slots(max(1, min(slots, k)))
            off = rng.choice([0, 2, 4])
            for i, s in enumerate(sl):
                nxt = sl[i + 1] if i + 1 < len(sl) else slots
                dur = min(nxt - s, npb * 3)
                if s % strong == 0:
                    off = rng.choice([0, 2, 4])
                else:
                    off = max(-3, min(7, off + rng.choice(steps)))
                motif.append((mb, s, dur, off))
        mut = 0.1 + 0.4 * cx
        for bi, deg in enumerate(degrees):
            dmap = nearest_degree(mel, deg.root)
            if bi == bars - 1:
                add(bi * bpb, max(1.0, bpb * 0.9), fold(scale_pitch(mel, dmap, base), -3), 60)
                continue
            for mb, s, dur, off in motif:
                if mb != bi % 2:
                    continue
                o = off
                if s % strong != 0 and rng.random() < mut:
                    o += rng.choice([-1, 1])
                p = fold(scale_pitch(mel, dmap + o, base), -3)
                add(tm(bi, s), dur * step * 0.95, p, 62 + rng.randrange(0, 14))

    elif mode == "Arp":
        kind = rng.choice(["up", "updown", "walk"])
        p_play = 0.55 + 0.45 * pop
        idx = 0
        for bi, deg in enumerate(degrees):
            ch = voicing(st, deg, base)
            tones = ch + [ch[0] + 12]
            L = len(tones)
            seq = list(range(L)) + list(range(L - 2, 0, -1))
            for i in range(slots):
                if kind == "up":
                    idx = i % L
                elif kind == "updown":
                    idx = seq[i % len(seq)]
                else:
                    idx = max(0, min(L - 1, idx + rng.choice([-1, 1, 1, 2, -2])))
                if i == 0 or rng.random() < p_play:
                    add(tm(bi, i), step * (1.6 + cx), tones[idx], 62 if i % npb == 0 else 52)

    elif mode == "Chord":
        for bi, deg in enumerate(degrees):
            ch = led_voicing(deg)
            hits = [0]
            if bpb >= 3 and rng.random() < min(0.85, pop * 1.3):
                hits.append(rng.choice([slots // 2, max(1, slots - npb)]))
                hits = sorted(set(hits))
            for hi_, h in enumerate(hits):
                end = hits[hi_ + 1] if hi_ + 1 < len(hits) else slots
                dur = (end - h) * step * 0.97
                for j, nn in enumerate(ch + [base + deg.root - 12]):
                    add(tm(bi, h) + j * 0.05, dur, nn, 56)

    elif mode == "Rhythm":
        for bi, deg in enumerate(degrees):
            ch = led_voicing(deg)
            k = int(round(1 + slots * (0.05 + 0.30 * pop) + rng.uniform(-0.5, 0.5)))
            sl = pick_slots(max(1, min(slots, k)), 1.0)
            for i, s in enumerate(sl):
                nxt = sl[i + 1] if i + 1 < len(sl) else slots
                dur = min(nxt - s, npb * 2) * step * 0.9
                for j, nn in enumerate(ch):
                    add(tm(bi, s) + j * 0.015, dur, nn, 56 + (8 if s == 0 else 0))

    elif mode == "Pad":
        for bi, deg in enumerate(degrees):
            for nn in led_voicing(deg, True):
                add(bi * bpb, bpb * 0.99, nn, 38, True)

    elif mode == "Bass":
        for bi, deg in enumerate(degrees):
            root = base + deg.root
            fifth = base + (deg.root + (6 if deg.q in ("dim", "m7b5", "dim7") else 7)) % 12
            if pop < 0.3:
                r = rng.random()
                half = bpb / 2.0
                if r < 0.55 or bpb < 4:
                    add(bi * bpb, bpb * 0.97, root, 66, True)
                elif r < 0.80:
                    add(bi * bpb, half * 0.97, root, 66, True)
                    add(bi * bpb + half, half * 0.95, fifth if rng.random() < 0.6 else root + 12, 58, True)
                else:
                    add(bi * bpb, (bpb - 1) * 0.97, root, 66, True)
                    add(bi * bpb + bpb - 1, 0.95, fifth, 56, True)
            else:
                k = int(round(1 + slots * 0.25 * pop + rng.uniform(-0.5, 0.5)))
                sl = pick_slots(max(1, min(slots, k)), 1.0)
                for i, s in enumerate(sl):
                    nxt = sl[i + 1] if i + 1 < len(sl) else slots
                    dur = min(nxt - s, npb * 2) * step * 0.95
                    p = root
                    r = rng.random()
                    if s != 0:
                        if r < 0.3 * (0.4 + cx):
                            p = fifth
                        elif r < 0.45 * (0.4 + cx):
                            p = root + 12
                    add(tm(bi, s), dur, p, 70 if s == 0 else 62, True)

    elif mode == "Drums":
        snares = [1, 3] if bpb >= 4 else [1]
        for bi in range(bars):
            b = bi * bpb
            add(b, 0.1, 36, 84, True)
            if rng.random() < 0.55:
                add(beat_t(bi, (bpb / 2.0 + 0.5) if bpb >= 4 else 1.5), 0.1, 36, 70, True)
            for sb in snares:
                add(b + sb, 0.1, 38, 62, True)
            if rng.random() < 0.05 + 0.25 * cx:
                add(b + bpb - 0.25, 0.1, 38, 34, True)
            for s in range(slots):
                if rng.random() < 0.4 + 0.55 * pop:
                    add(tm(bi, s), 0.1, 42, 48 if s % npb == 0 else 36, True)
            if rng.random() < 0.25:
                add(beat_t(bi, bpb - 0.5), 0.3, 46, 40, True)

    return notes


def generate_section(st, tracks, seed, chords=None, var=0):
    custom = chords is not None
    if chords is None:
        chords = gen_chords(st, random.Random(seed * 1009 + 5), st.bars)
    sec = Section(bars=len(chords), bpb=st.bpb, npb=st.npb, chords=list(chords), seed=seed,
                  custom=custom, var=var)
    regen_all(sec, st, tracks)
    return sec


def regen_all(sec, st, tracks):
    sec.notes = [gen_track(st, cfg, sec.chords, _track_rng(sec.seed, i, cfg, sec.var), sec.bpb, sec.npb)
                 for i, cfg in enumerate(tracks)]


def regen_track(sec, st, tracks, i):
    cfg = tracks[i]
    cfg.regen += 1
    sec.notes[i] = gen_track(st, cfg, sec.chords, _track_rng(sec.seed, i, cfg, sec.var), sec.bpb, sec.npb)


def set_chords(sec, st, tracks, chords):
    """Use hand-picked / typed chords (one per bar). They follow the Key setting."""
    sec.chords = list(chords)
    sec.custom = True
    regen_all(sec, st, tracks)


def regenerate(sec, st, tracks):
    """Rebuild a section after a setting changed. Hand-picked chords are kept
    (and transpose with the Key); generated chords are rebuilt from the seed."""
    chords = None
    if sec.custom:
        chords = [sec.chords[i % len(sec.chords)] for i in range(st.bars)]
    new = generate_section(st, tracks, sec.seed, chords, sec.var)
    return new


def vary(sec, st, tracks):
    """Keep chords, bass, pad and drums; give melody-type tracks new ideas."""
    for i, cfg in enumerate(tracks):
        if cfg.mode in ("Melody", "Arp", "Rhythm"):
            regen_track(sec, st, tracks, i)


# ---- full-length arrangement (Spotify single / YouTube long video) -----------------------

_PATTERN = ["A", "A2", "B", "A2", "A", "B2"]
PART_NAMES = {"Intro": "Intro", "Outro": "Outro", "A": "Theme", "A2": "Theme (new melody)",
              "B": "Contrast", "B2": "Contrast (new melody)"}


def _ramp(sec, f0, f1):
    """Fade velocities linearly across a section (a soft fade in / out)."""
    total = float(sec.total_beats)
    for ns in sec.notes:
        for n in ns:
            f = f0 + (f1 - f0) * min(1.0, max(0.0, n.start / total))
            n.vel = max(1, min(127, int(n.vel * f)))


def _thin(sec, st, tracks, drop_modes):
    """Empty the tracks whose mode is in drop_modes, but never leave the section silent."""
    ok = audible(tracks)
    kept = []
    for i, cfg in enumerate(tracks):
        if cfg.mode in drop_modes:
            sec.notes[i] = []
        elif ok[i] and sec.notes[i]:
            kept.append(i)
    if not kept:   # e.g. a lofi preset with only bass left: bring the melody back
        for i, cfg in enumerate(tracks):
            if ok[i] and cfg.mode in ("Melody", "Arp"):
                sec.notes[i] = gen_track(st, cfg, sec.chords, _track_rng(sec.seed, i, cfg, sec.var),
                                         sec.bpb, sec.npb)



_EXT_MAJOR = ["", "add9", "6", "maj7"]
_EXT_MINOR = ["m", "m7", "madd9"]


def vary_chords(chords, rng):
    """Same harmony, fresher colour: swap in extensions, and sometimes lead back with the
    dominant (V) at the end of a 4-bar phrase."""
    out = []
    for c in chords:
        q = c.q
        if rng.random() < 0.45:
            if q == "":
                q = rng.choice(_EXT_MAJOR)
            elif q == "m":
                q = rng.choice(_EXT_MINOR)
        out.append(Chord(c.root, q))
    for i in range(3, len(out) - 1, 4):
        if rng.random() < 0.35:
            out[i] = Chord(7, "")
    return out


def build_arrangement(st, tracks, target_sec, home, base_seed):
    """Turn one idea into a full track of about target_sec seconds:
    Intro -> Theme / Contrast sections -> Outro.  The Theme is your chords; Contrast parts
    rotate through other progressions; repeats get new chord colours, new voicings and
    new bass / chord rhythms so nothing loops identically.
    Returns (sections, parts); parts = [(label, kind, bars, start_sec, end_sec)]."""
    rng = random.Random(base_seed * 31 + 7)
    bar_sec = st.bpb * 60.0 / st.bpm
    total_bars = max(12, int(round(target_sec / bar_sec)))
    sec_bars = st.bars if st.bars >= 4 else 8
    sizes, rem = [], total_bars
    while rem >= 4:
        b = min(sec_bars, rem)
        sizes.append(b)
        rem -= b
    while len(sizes) < 3:
        sizes.append(sec_bars)

    def cycle(chords, n):
        return [chords[i % len(chords)] for i in range(n)]

    # other progressions for the Contrast parts (never the same as the Theme)
    home_key = tuple(cycle(home, sec_bars)[:4])
    tonic = degree_chord(st, 0, st.sevenths)
    alts = []
    for pr in (st.progs or PROGRESSIONS[st.scale]):
        cand = [degree_chord(st, pr[i % len(pr)], st.sevenths) for i in range(sec_bars)]
        cand[-1] = tonic
        if tuple(cand[:4]) != home_key and cand not in alts:
            alts.append(cand)
    rng.shuffle(alts)
    if not alts:
        alts = [gen_chords(st, rng, sec_bars)]

    sections, parts, acc = [], [], 0.0
    seen = {}
    n = len(sizes)
    for k, b in enumerate(sizes):
        if k == 0:
            kind = "Intro"
        elif k == n - 1:
            kind = "Outro"
        else:
            kind = _PATTERN[(k - 1) % len(_PATTERN)]
        m = seen.get(kind, 0)
        seen[kind] = m + 1
        if kind in ("B", "B2"):
            bi = seen.get("B", 0) + seen.get("B2", 0) - 1
            chords = cycle(alts[bi % len(alts)], b)
        else:
            chords = cycle(home, b)
        if kind in ("A2", "B2"):
            chords = vary_chords(chords, rng)
        if kind == "Outro":
            chords[-1] = tonic                               # come home on the tonic
        if kind in ("A", "B"):
            seed = base_seed + (0 if m % 3 == 0 else 13 * m) + (7 if kind == "B" else 0)
        else:
            seed = base_seed + 101 * (k + 1)
        wave = 0.8 + 0.4 * (0.5 + 0.5 * math.sin(2 * math.pi * k / 10.0))
        stk = replace(st, population=max(0.05, min(1.0, st.population * wave)))
        sec = generate_section(stk, tracks, seed, chords, var=k)
        if kind == "Intro":
            _thin(sec, stk, tracks, ("Melody", "Arp", "Rhythm", "Drums"))
            _ramp(sec, 0.3, 1.0)
        elif kind == "Outro":
            _thin(sec, stk, tracks, ("Rhythm", "Drums"))
            _ramp(sec, 1.0, 0.12)
        sections.append(sec)
        span = b * bar_sec
        parts.append((PART_NAMES[kind], kind, b, acc, acc + span))
        acc += span
    return sections, parts


# ---- MIDI file ---------------------------------------------------------------------------

def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _meta(kind, data):
    return bytes([0xFF, kind]) + _vlq(len(data)) + data


def _chunk(events, end_tick):
    events.sort(key=lambda e: (e[0], e[1]))
    data = bytearray()
    last = 0
    for tick, _, b in events:
        data += _vlq(tick - last) + b
        last = tick
    data += _vlq(max(0, end_tick - last)) + b"\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)


def to_midi(sections, st, tracks) -> bytes:
    total_beats = sum(s.total_beats for s in sections)
    end_tick = int(total_beats * PPQ)
    tempo = int(60_000_000 / st.bpm)
    chunks = [_chunk([
        (0, 0, _meta(0x03, b"CalmComposer")),
        (0, 0, _meta(0x51, tempo.to_bytes(3, "big"))),
        (0, 0, _meta(0x58, bytes([sections[0].bpb, 2, 24, 8]))),
    ], end_tick)]
    ok = audible(tracks)
    for i, cfg in enumerate(tracks):
        if not ok[i]:
            continue
        ch = channel_of(i, cfg)
        ev = [(0, 0, _meta(0x03, ("Track %d %s" % (i + 1, cfg.mode)).encode()))]
        if cfg.mode != "Drums":
            ev.append((0, -1, bytes([0xC0 | ch, cfg.program])))
        count = 0
        offset = 0.0
        for sec in sections:
            for n in sec.notes[i]:
                on = int(round((offset + n.start) * PPQ))
                off = on + max(1, int(round(n.dur * PPQ)))
                v = eff_vel(n.vel, cfg)
                ev.append((on, 1, bytes([0x90 | ch, n.pitch, v])))
                ev.append((off, 0, bytes([0x80 | ch, n.pitch, 0])))
                count += 1
            offset += sec.total_beats
        if count:
            chunks.append(_chunk(ev, end_tick))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), PPQ)
    return header + b"".join(chunks)


def to_messages(sections, st, tracks):
    """Time-sorted (sec, order, status, d1, d2, track_index) for live playback.
    Velocities are raw; the player applies volume / mute live."""
    spb = 60.0 / st.bpm
    msgs = []
    offset = 0.0
    for sec in sections:
        for i, cfg in enumerate(tracks):
            ch = channel_of(i, cfg)
            for n in sec.notes[i]:
                msgs.append(((offset + n.start) * spb, 1, 0x90 | ch, n.pitch, n.vel, i))
                msgs.append(((offset + n.start + n.dur) * spb, 0, 0x80 | ch, n.pitch, 0, i))
        offset += sec.total_beats
    msgs.sort(key=lambda m: (m[0], m[1]))
    return msgs
