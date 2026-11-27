"""CalmComposer engine: procedural MIDI generator for calm piano,
piano + nature and relaxing lofi.  Pure Python, no dependencies."""
import random
import struct
from dataclasses import dataclass, field

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALES = {
    "Major": [0, 2, 4, 5, 7, 9, 11],
    "Minor": [0, 2, 3, 5, 7, 8, 10],
    "Dorian": [0, 2, 3, 5, 7, 9, 10],
    "Lydian": [0, 2, 4, 6, 7, 9, 11],
    "Pentatonic Major": [0, 2, 4, 7, 9],
    "Pentatonic Minor": [0, 3, 5, 7, 10],
}
# Pentatonic scales take their chords from the matching 7-note scale.
PARENT = {"Pentatonic Major": "Major", "Pentatonic Minor": "Minor"}

# Chord progressions as 0-based scale degrees (one chord per bar).
_MAJOR = [[0, 5, 3, 4], [0, 4, 5, 3], [3, 4, 2, 5], [0, 2, 3, 4], [0, 3, 0, 4], [5, 3, 0, 4]]
_MINOR = [[0, 5, 2, 6], [0, 3, 6, 2], [0, 5, 3, 6], [0, 2, 5, 6], [0, 3, 4, 0], [5, 6, 0, 0]]
_DORIAN = [[0, 3, 0, 3], [0, 3, 6, 0], [0, 6, 3, 0], [0, 3, 2, 6]]
_LYDIAN = [[0, 1, 0, 1], [0, 1, 4, 0], [0, 4, 1, 0], [0, 1, 5, 0]]
PROGRESSIONS = {
    "Major": _MAJOR, "Pentatonic Major": _MAJOR,
    "Minor": _MINOR, "Pentatonic Minor": _MINOR,
    "Dorian": _DORIAN, "Lydian": _LYDIAN,
}

TRACKS = ["Chords", "Melody", "Bass", "Pad", "Drums"]
CHANNEL = {"Chords": 0, "Melody": 1, "Bass": 2, "Pad": 3, "Drums": 9}
PPQ = 480

# General MIDI programs (0-based): 0 piano, 4 electric piano, 32 acoustic bass,
# 33 finger bass, 89 warm pad.
PRESETS = {
    "Calm Piano": dict(
        bpm=68, scale="Major", bars=8, complexity=0.30, swing=0.0, humanize=0.4,
        chord_style="arp", tracks=["Chords", "Melody", "Bass", "Pad"],
        programs={"Chords": 0, "Melody": 0, "Bass": 32, "Pad": 89}),
    "Piano + Nature": dict(
        bpm=56, scale="Major", bars=8, complexity=0.15, swing=0.0, humanize=0.5,
        chord_style="pad", tracks=["Chords", "Melody", "Pad"],
        programs={"Chords": 0, "Melody": 0, "Bass": 32, "Pad": 89}),
    "Relaxing Lofi": dict(
        bpm=78, scale="Minor", bars=8, complexity=0.45, swing=0.5, humanize=0.6,
        chord_style="lofi", tracks=["Chords", "Melody", "Bass", "Drums"],
        programs={"Chords": 4, "Melody": 0, "Bass": 33, "Pad": 89}),
}


@dataclass
class Note:
    track: str
    start: float   # in beats
    dur: float     # in beats
    pitch: int
    vel: int


@dataclass
class Params:
    preset: str = "Calm Piano"
    key: int = 0
    scale: str = "Major"
    bpm: int = 68
    bars: int = 8
    complexity: float = 0.3
    swing: float = 0.0
    humanize: float = 0.4
    seed: int = 1
    chord_style: str = "arp"          # arp | pad | lofi
    tracks: tuple = ("Chords", "Melody", "Pad", "Bass")


@dataclass
class Song:
    params: Params
    notes: list = field(default_factory=list)
    chord_names: list = field(default_factory=list)
    programs: dict = field(default_factory=dict)

    @property
    def bpm(self):
        return self.params.bpm

    @property
    def bars(self):
        return self.params.bars

    @property
    def total_beats(self):
        return self.params.bars * 4

    @property
    def length_sec(self):
        return self.total_beats * 60.0 / self.params.bpm


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


def generate(p: Params) -> Song:
    rng = random.Random(p.seed)
    bars = p.bars
    total = bars * 4
    c = max(0.0, min(1.0, p.complexity))
    enabled = set(p.tracks)
    parent = SCALES[PARENT.get(p.scale, p.scale)]
    mel_scale = SCALES[p.scale]
    shift = p.swing * 0.33   # up to a triplet feel on off-beat eighths

    song = Song(params=p)
    song.programs = dict(PRESETS.get(p.preset, PRESETS["Calm Piano"])["programs"])

    def sw(t):
        return t + shift if abs((t % 1.0) - 0.5) < 1e-6 else t

    def add(track, start, dur, pitch, vel, tight=False):
        if track not in enabled:
            return
        h = p.humanize * (0.4 if tight else 1.0)
        s = max(0.0, start + rng.uniform(-1, 1) * 0.025 * h)
        d = min(dur, total - s)
        if d <= 0.02:
            return
        v = max(1, min(127, int(vel + rng.uniform(-1, 1) * 10 * h)))
        song.notes.append(Note(track, s, d, int(pitch), v))

    # ---- chord progression -------------------------------------------------
    prog = rng.choice(PROGRESSIONS[p.scale])
    degrees = [prog[i % len(prog)] for i in range(bars)]
    degrees[-1] = 0                      # end on the tonic

    seventh = p.chord_style == "lofi"

    def voicing(deg, sev):
        ks = (0, 2, 4, 6) if sev else (0, 2, 4)
        notes = [scale_pitch(parent, deg + k, 48 + p.key) for k in ks]
        while max(notes) > 72:
            notes = [n - 12 for n in notes]
        return notes

    for deg in degrees:
        song.chord_names.append(chord_name(voicing(deg, seventh), seventh))

    # ---- chords / pad / bass, bar by bar -------------------------------------
    for bi, deg in enumerate(degrees):
        b = bi * 4.0
        notes = voicing(deg, seventh)
        n0 = notes[0]

        if p.chord_style == "arp":
            t = [n0, notes[1], notes[2], n0 + 12]
            add("Chords", b, 3.9, n0 - 12, 50)
            if c < 0.4:
                for beat, ti in [(0, 0), (1, 1), (2, 2), (3, 1)]:
                    if beat == 0 or rng.random() > 0.1:
                        add("Chords", b + beat, 1.6, t[ti], 66 if beat == 0 else 58)
            else:
                pat = [0, 1, 2, 3, 2, 1, 2, 1]
                for i, ti in enumerate(pat):
                    if i == 0 or rng.random() > 0.08:
                        add("Chords", b + sw(i / 2), 1.0, t[ti], 64 if i % 4 == 0 else 54)
        elif p.chord_style == "pad":
            for i, n in enumerate(notes + [n0 - 12]):
                add("Chords", b + i * 0.06, 3.9, n, 56)
        else:  # lofi
            add("Chords", b, 1.5, n0 - 12, 50)
            for i, n in enumerate(notes):
                add("Chords", b + i * 0.02, 1.4, n, 64)
            cands = [1.5, 2.5, 3.5]
            rng.shuffle(cands)
            picks = 0
            for pos in cands:
                if picks < 2 and rng.random() < 0.35 + 0.3 * c:
                    picks += 1
                    for n in notes:
                        add("Chords", b + sw(pos), 0.7, n, 52)

        # warm pad: triad an octave up, very soft
        pad = [n + 12 for n in voicing(deg, False)]
        while max(pad) > 81:
            pad = [n - 12 for n in pad]
        for n in pad:
            add("Pad", b, 3.95, n, 34, tight=True)

        # bass
        root_b = scale_pitch(parent, deg, 36 + p.key)
        fifth_b = scale_pitch(parent, deg + 4, 36 + p.key)
        while root_b > 47:
            root_b -= 12
        while fifth_b > 47:
            fifth_b -= 12
        if p.chord_style == "lofi":
            add("Bass", b, 1.5, root_b, 82, tight=True)
            if rng.random() < 0.6:
                add("Bass", b + sw(2.5), 1.0, fifth_b if rng.random() < 0.5 else root_b, 70, tight=True)
            if c > 0.5 and rng.random() < 0.4:
                add("Bass", b + sw(3.5), 0.5, root_b, 64, tight=True)
        else:
            add("Bass", b, 3.9, root_b, 62, tight=True)
            if rng.random() < c * 0.5:
                add("Bass", b + 2, 1.8, fifth_b, 56, tight=True)

    # ---- melody (a 2-bar motif, re-fitted to each chord) -----------------------
    motif = []
    for mb in range(2):
        k = max(1, min(7, int(round(1 + c * 5 + rng.uniform(-1, 1)))))
        slots = set()
        if rng.random() < 0.75:
            slots.add(0)
        while len(slots) < k:
            slots.add(rng.randrange(8))
        slots = sorted(slots)
        off = rng.choice([0, 2, 4])
        for i, s in enumerate(slots):
            nxt = slots[i + 1] if i + 1 < len(slots) else 8
            dur = min(nxt - s, 6)
            if s in (0, 4):
                off = rng.choice([0, 2, 4])
            else:
                off = max(-2, min(6, off + rng.choice([-2, -1, 1, 2])))
            motif.append((mb, s, dur, off))

    n_m = len(mel_scale)
    for bi, deg in enumerate(degrees):
        b = bi * 4.0
        dmap = deg if n_m == 7 else int(round(deg * n_m / 7.0))
        if bi == bars - 1:
            pitch = scale_pitch(mel_scale, dmap, 60 + p.key)
            while pitch > 84:
                pitch -= 12
            add("Melody", b, 3.5, pitch, 60)
            continue
        for mb, s, dur, off in motif:
            if mb != bi % 2:
                continue
            o = off
            if s not in (0, 4) and rng.random() < 0.2:
                o += rng.choice([-1, 1])
            pitch = scale_pitch(mel_scale, dmap + o, 60 + p.key)
            while pitch > 84:
                pitch -= 12
            while pitch < 57:
                pitch += 12
            add("Melody", b + sw(s / 2.0), dur / 2.0 * 0.95, pitch, 62 + rng.randrange(0, 14))

    # ---- drums (soft boom-bap) ----------------------------------------------------
    for bi in range(bars):
        b = bi * 4.0
        add("Drums", b, 0.1, 36, 84, tight=True)
        if rng.random() < 0.55:
            add("Drums", b + sw(2.5), 0.1, 36, 70, tight=True)
        if rng.random() < 0.15 + 0.2 * c:
            add("Drums", b + 1.75, 0.1, 36, 60, tight=True)
        add("Drums", b + 1, 0.1, 38, 62, tight=True)
        add("Drums", b + 3, 0.1, 38, 64, tight=True)
        if rng.random() < 0.25 * c + 0.05:
            add("Drums", b + 3.75, 0.1, 38, 34, tight=True)
        for i in range(8):
            if rng.random() < 0.88:
                add("Drums", b + sw(i / 2.0), 0.1, 42, 48 if i % 2 == 0 else 36, tight=True)
        if rng.random() < 0.25:
            add("Drums", b + sw(3.5), 0.3, 46, 40, tight=True)

    song.notes.sort(key=lambda n: (n.start, n.pitch))
    return song


# ---- MIDI file --------------------------------------------------------------------

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


def to_midi(song: Song) -> bytes:
    total_ticks = int(song.total_beats * PPQ)
    tempo = int(60_000_000 / song.bpm)
    tempo_ev = [
        (0, 0, _meta(0x03, b"CalmComposer")),
        (0, 0, _meta(0x51, tempo.to_bytes(3, "big"))),
        (0, 0, _meta(0x58, bytes([4, 2, 24, 8]))),
    ]
    chunks = [_chunk(tempo_ev, total_ticks)]
    for tr in TRACKS:
        notes = [n for n in song.notes if n.track == tr]
        if not notes:
            continue
        ch = CHANNEL[tr]
        ev = [(0, 0, _meta(0x03, tr.encode()))]
        if tr != "Drums":
            ev.append((0, -1, bytes([0xC0 | ch, song.programs.get(tr, 0)])))
        for n in notes:
            on = int(round(n.start * PPQ))
            off = on + max(1, int(round(n.dur * PPQ)))
            ev.append((on, 1, bytes([0x90 | ch, n.pitch, n.vel])))
            ev.append((off, 0, bytes([0x80 | ch, n.pitch, 0])))
        chunks.append(_chunk(ev, total_ticks))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), PPQ)
    return header + b"".join(chunks)


def to_messages(song: Song):
    """Time-sorted (seconds, status, data1, data2) list for live playback."""
    spb = 60.0 / song.bpm
    msgs = []
    used = {n.track for n in song.notes}
    for tr in used:
        if tr != "Drums":
            msgs.append((0.0, -1, 0xC0 | CHANNEL[tr], song.programs.get(tr, 0), 0))
    for n in song.notes:
        ch = CHANNEL[n.track]
        msgs.append((n.start * spb, 1, 0x90 | ch, n.pitch, n.vel))
        msgs.append(((n.start + n.dur) * spb, 0, 0x80 | ch, n.pitch, 0))
    msgs.sort(key=lambda m: (m[0], m[1]))
    return [(t, st, d1, d2) for t, _, st, d1, d2 in msgs]
