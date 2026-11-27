"""CalmComposer engine v2: procedural MIDI generator for calm piano,
piano + nature and relaxing lofi.  Pure Python, no dependencies.

Model: Settings (global) + 6 TrackCfg (one per track) + Sections (A-F).
A Section holds its chord progression and the notes of every track.
"""
import random
import struct
from dataclasses import dataclass, field

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]

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


@dataclass
class Section:
    bars: int
    bpb: int
    npb: int
    degrees: list
    notes: list = field(default_factory=list)   # one list[Note] per track
    seed: int = 1

    @property
    def total_beats(self):
        return self.bars * self.bpb


def scale_pitch(scale, idx, root):
    n = len(scale)
    return root + scale[idx % n] + 12 * (idx // n)


def chord_name(notes, seventh):
    root = NOTE_NAMES[notes[0] % 12]
    third = notes[1] - notes[0]
    fifth = notes[2] - notes[0]
    minor = third == 3
    if seventh and len(notes) > 3:
        s = notes[3] - notes[0]
        if not minor:
            return root + ("maj7" if s == 11 else "7")
        return root + ("m7" if s == 10 else "m(maj7)" if s == 11 else "dim7")
    if fifth == 6:
        return root + "dim"
    return root + ("m" if minor else "")


def voicing(st, deg, base, sevenths):
    parent = SCALES[PARENT.get(st.scale, st.scale)]
    ks = (0, 2, 4, 6) if sevenths else (0, 2, 4)
    notes = [scale_pitch(parent, deg + k, base) for k in ks]
    while max(notes) > base + 24:
        notes = [n - 12 for n in notes]
    return notes


def chord_name_for(st, deg):
    return chord_name(voicing(st, deg, 48 + st.key, st.sevenths), st.sevenths)


def channel_of(i, cfg):
    return 9 if cfg.mode == "Drums" else i


def audible(tracks):
    solos = any(t.solo for t in tracks)
    return [(t.solo if solos else not t.mute) for t in tracks]


def eff_vel(vel, cfg):
    return max(1, min(127, int(vel * cfg.vol / 100.0)))


# ---- generation --------------------------------------------------------------------

def gen_degrees(st, rng, bars):
    prog = rng.choice(PROGRESSIONS[st.scale])
    degrees = [prog[i % len(prog)] for i in range(bars)]
    degrees[-1] = 0
    return degrees


def _track_rng(seed, i, cfg):
    return random.Random(seed * 131 + i * 17 + cfg.regen * 7919)


def gen_track(st, cfg, degrees, rng, bpb, npb):
    bars = len(degrees)
    total = bars * bpb
    slots = bpb * npb
    step = 1.0 / npb
    cx = st.complexity
    pop = st.population
    parent = SCALES[PARENT.get(st.scale, st.scale)]
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

    mode = cfg.mode

    if mode == "Melody":
        mel = SCALES[st.scale]
        n = len(mel)
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
            dmap = deg if n == 7 else int(round(deg * n / 7.0))
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
            ch = voicing(st, deg, base, st.sevenths)
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
            ch = voicing(st, deg, base, st.sevenths)
            hits = [0]
            if pop > 0.45 and bpb >= 4:
                hits.append(slots // 2)
            for hi_, h in enumerate(hits):
                end = hits[hi_ + 1] if hi_ + 1 < len(hits) else slots
                dur = (end - h) * step * 0.97
                for j, nn in enumerate(ch + [ch[0] - 12]):
                    add(tm(bi, h) + j * 0.05, dur, nn, 56)

    elif mode == "Rhythm":
        for bi, deg in enumerate(degrees):
            ch = voicing(st, deg, base, st.sevenths)
            k = int(round(1 + slots * (0.05 + 0.30 * pop) + rng.uniform(-0.5, 0.5)))
            sl = pick_slots(max(1, min(slots, k)), 1.0)
            for i, s in enumerate(sl):
                nxt = sl[i + 1] if i + 1 < len(sl) else slots
                dur = min(nxt - s, npb * 2) * step * 0.9
                for j, nn in enumerate(ch):
                    add(tm(bi, s) + j * 0.015, dur, nn, 56 + (8 if s == 0 else 0))

    elif mode == "Pad":
        for bi, deg in enumerate(degrees):
            for nn in voicing(st, deg, base, False):
                add(bi * bpb, bpb * 0.99, nn, 38, True)

    elif mode == "Bass":
        for bi, deg in enumerate(degrees):
            root = base + ((scale_pitch(parent, deg, base) - base) % 12)
            fifth = base + ((scale_pitch(parent, deg + 4, base) - base) % 12)
            if pop < 0.3:
                add(bi * bpb, bpb * 0.97, root, 66, True)
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


def generate_section(st, tracks, seed, degrees=None):
    if degrees is None:
        degrees = gen_degrees(st, random.Random(seed * 1009 + 5), st.bars)
    sec = Section(bars=len(degrees), bpb=st.bpb, npb=st.npb, degrees=list(degrees), seed=seed)
    regen_all(sec, st, tracks)
    return sec


def regen_all(sec, st, tracks):
    sec.notes = [gen_track(st, cfg, sec.degrees, _track_rng(sec.seed, i, cfg), sec.bpb, sec.npb)
                 for i, cfg in enumerate(tracks)]


def regen_track(sec, st, tracks, i):
    cfg = tracks[i]
    cfg.regen += 1
    sec.notes[i] = gen_track(st, cfg, sec.degrees, _track_rng(sec.seed, i, cfg), sec.bpb, sec.npb)


def set_degrees(sec, st, tracks, degrees):
    sec.degrees = list(degrees)
    regen_all(sec, st, tracks)


def vary(sec, st, tracks):
    """Keep chords, bass, pad and drums; give melody-type tracks new ideas."""
    for i, cfg in enumerate(tracks):
        if cfg.mode in ("Melody", "Arp", "Rhythm"):
            regen_track(sec, st, tracks, i)


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
