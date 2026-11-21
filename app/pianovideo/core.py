"""Núcleo do PianoVideo: transcrição (áudio -> notas), síntese (notas -> áudio)
e renderização (notas -> vídeo de notas caindo)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field

import numpy as np

# --------------------------------------------------------------------------- #
# Caminhos de recursos (funciona tanto rodando o .py quanto empacotado)
# --------------------------------------------------------------------------- #

def resource_dir() -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return base
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _find(*names: str) -> str:
    """Procura um recurso perto do executável/projeto."""
    candidates = [resource_dir()]
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates += [exe_dir, os.path.join(exe_dir, "..", "Resources")]
    for c in candidates:
        p = os.path.join(c, *names)
        if os.path.exists(p):
            return os.path.abspath(p)
    return os.path.join(resource_dir(), *names)


def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # evita janela preta no Windows


def decode_audio(path: str, sr: int, mono: bool = True) -> np.ndarray:
    """Decodifica qualquer áudio (wav, mp3, ...) para float32 via ffmpeg."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path, "-f", "f32le",
           "-ac", "1" if mono else "2", "-ar", str(sr), "-"]
    out = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError("Não consegui ler o áudio: " + out.stderr.decode(errors="ignore"))
    data = np.frombuffer(out.stdout, dtype=np.float32)
    return data if mono else data.reshape(-1, 2)


@dataclass
class Note:
    pitch: int        # MIDI 21..108
    start: float      # segundos (tecla pressionada)
    end: float        # segundos (tecla solta)
    velocity: int     # 1..127
    sound_end: float = 0.0  # fim do som (considerando pedal)


@dataclass
class Settings:
    width: int = 1920
    height: int = 1080
    fps: int = 60
    fall_seconds: float = 3.0       # tempo que a nota leva do topo até o teclado
    lead_in: float = 3.0            # silêncio antes da música (para ver as notas caindo)
    tail: float = 2.0
    left_color: tuple = (66, 165, 245)    # mão esquerda (abaixo do Dó central)
    right_color: tuple = (102, 214, 110)  # mão direita
    split_note: int = 60
    background: tuple = (18, 18, 24)
    crf: int = 18
    save_midi: bool = True


# --------------------------------------------------------------------------- #
# 1) Transcrição
# --------------------------------------------------------------------------- #

def transcribe(audio_path: str, progress=lambda f, msg: None) -> list[Note]:
    import torch
    import piano_transcription_inference.inference as pti
    from piano_transcription_inference import PianoTranscription, sample_rate

    progress(0.0, "Carregando áudio...")
    audio = decode_audio(audio_path, sample_rate)
    if audio.size == 0:
        raise RuntimeError("O arquivo de áudio está vazio.")

    total_segments = [1]

    def forward_with_progress(model, x, batch_size):
        output = {}
        device = next(model.parameters()).device
        n = len(x)
        total_segments[0] = n
        model.eval()
        for i in range(0, n, batch_size):
            progress(i / n, f"Transcrevendo notas... {int(100 * i / n)}%")
            batch = torch.as_tensor(x[i:i + batch_size], dtype=torch.float32, device=device)
            with torch.no_grad():
                out = model(batch)
            for k, v in out.items():
                output.setdefault(k, []).append(v.detach().cpu().numpy())
        return {k: np.concatenate(v, axis=0) for k, v in output.items()}

    pti.forward = forward_with_progress

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    progress(0.0, "Carregando modelo de IA...")
    model_path = _find("models", "piano_model.pth")
    if not os.path.exists(model_path):
        raise RuntimeError(f"Modelo não encontrado em {model_path}")
    transcriptor = PianoTranscription(device=torch.device(device), checkpoint_path=model_path)
    result = transcriptor.transcribe(audio, None)
    progress(1.0, "Transcrição concluída.")

    notes = [Note(int(e["midi_note"]), float(e["onset_time"]), float(e["offset_time"]),
                  int(e["velocity"])) for e in result["est_note_events"]]
    notes = [n for n in notes if 21 <= n.pitch <= 108 and n.end > n.start]
    notes.sort(key=lambda n: (n.start, n.pitch))
    _apply_pedal(notes, result.get("est_pedal_events") or [])
    return notes


def _apply_pedal(notes: list[Note], pedals: list[dict]) -> None:
    """Calcula até quando cada nota soa considerando o pedal de sustentação."""
    pedal = sorted((float(p["onset_time"]), float(p["offset_time"])) for p in pedals)
    next_same: dict[int, float] = {}
    for n in sorted(notes, key=lambda n: -n.start):
        end = n.end
        for a, b in pedal:
            if a <= n.end <= b:
                end = max(end, b)
                break
        nxt = next_same.get(n.pitch)
        if nxt is not None:
            end = min(end, nxt)
        n.sound_end = max(n.end, end)
        next_same[n.pitch] = n.start


def write_midi(notes: list[Note], path: str) -> None:
    import mido
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))  # 120 bpm => 960 ticks/s
    ev = []
    for n in notes:
        ev.append((n.start, 1, n.pitch, n.velocity))
        ev.append((n.end, 0, n.pitch, 0))
    ev.sort()
    last = 0
    for t, on, p, v in ev:
        tick = int(round(t * 960))
        tr.append(mido.Message("note_on" if on else "note_off", note=p, velocity=v,
                               time=max(0, tick - last)))
        last = tick
    mid.save(path)


# --------------------------------------------------------------------------- #
# 2) Síntese (recria o áudio a partir das notas transcritas)
# --------------------------------------------------------------------------- #

SR = 44100
_SAMPLE_NOTES = {"C": 0, "Ds": 3, "Fs": 6, "A": 9}


def _load_samples() -> dict[int, np.ndarray]:
    folder = _find("samples")
    bank = {}
    for fname in os.listdir(folder):
        if not fname.endswith(".mp3"):
            continue
        name, octave = fname[:-5], int(fname[-5])
        if name not in _SAMPLE_NOTES:
            continue
        midi = 12 * (octave + 1) + _SAMPLE_NOTES[name]
        bank[midi] = decode_audio(os.path.join(folder, fname), SR)
    if not bank:
        raise RuntimeError("Amostras de piano não encontradas.")
    return bank


def synthesize(notes: list[Note], duration: float, offset: float,
               progress=lambda f, msg: None) -> np.ndarray:
    bank = _load_samples()
    keys = np.array(sorted(bank))
    out = np.zeros(int((duration + 1) * SR) + 1, dtype=np.float32)
    release = 0.25
    cache: dict[int, np.ndarray] = {}

    def sample_for(pitch: int) -> np.ndarray:
        if pitch not in cache:
            src = int(keys[np.argmin(np.abs(keys - pitch))])
            s = bank[src]
            ratio = 2.0 ** ((pitch - src) / 12.0)
            if ratio == 1.0:
                cache[pitch] = s
            else:
                idx = np.arange(0, len(s) - 1, ratio)
                cache[pitch] = np.interp(idx, np.arange(len(s)), s).astype(np.float32)
        return cache[pitch]

    for i, n in enumerate(notes):
        if i % 200 == 0:
            progress(i / max(1, len(notes)), "Recriando o áudio...")
        s = sample_for(n.pitch)
        length = min(len(s), int((n.sound_end - n.start + release) * SR))
        if length <= 0:
            continue
        seg = s[:length].copy()
        rel = min(int(release * SR), length)
        seg[length - rel:] *= np.linspace(1, 0, rel, dtype=np.float32) ** 2
        gain = (max(1, n.velocity) / 127.0) ** 1.7
        st = int((n.start + offset) * SR)
        if st >= len(out):
            continue
        seg = seg[:len(out) - st]
        out[st:st + len(seg)] += seg * gain

    peak = float(np.max(np.abs(out))) or 1.0
    out = out / peak * 0.95 * 1.4
    out = np.tanh(out) * 0.92  # limitador suave
    progress(1.0, "Áudio recriado.")
    return out


def write_wav(path: str, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# --------------------------------------------------------------------------- #
# 3) Renderização do vídeo
# --------------------------------------------------------------------------- #

def _is_black(p: int) -> bool:
    return p % 12 in (1, 3, 6, 8, 10)


@dataclass
class Keyboard:
    width: int
    top: int
    height: int
    x0: np.ndarray = field(default=None)
    x1: np.ndarray = field(default=None)

    def __post_init__(self):
        whites = [p for p in range(21, 109) if not _is_black(p)]
        ww = self.width / len(whites)
        self.white_w = ww
        self.x0 = np.zeros(128)
        self.x1 = np.zeros(128)
        wi = 0
        for p in range(21, 109):
            if _is_black(p):
                bw = ww * 0.6
                c = wi * ww
                # pequenos deslocamentos como em um piano real
                shift = {1: -0.08, 3: 0.08, 6: -0.1, 8: 0.0, 10: 0.1}[p % 12] * bw
                self.x0[p] = c - bw / 2 + shift
                self.x1[p] = c + bw / 2 + shift
            else:
                self.x0[p] = wi * ww
                self.x1[p] = (wi + 1) * ww
                wi += 1


def _mix(img, y0, y1, x0, x1, color, alpha=1.0):
    h, w = img.shape[:2]
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    x0, x1 = max(0, int(round(x0))), min(w, int(round(x1)))
    if y1 <= y0 or x1 <= x0:
        return
    if alpha >= 1.0:
        img[y0:y1, x0:x1] = color
    else:
        reg = img[y0:y1, x0:x1].astype(np.float32)
        img[y0:y1, x0:x1] = (reg * (1 - alpha) + np.array(color, np.float32) * alpha).astype(np.uint8)


def _corner_mask(r: int) -> np.ndarray:
    yy, xx = np.mgrid[0:r, 0:r] + 0.5
    d = np.sqrt((r - xx) ** 2 + (r - yy) ** 2)
    return np.clip(r - d + 0.5, 0, 1).astype(np.float32)  # canto superior esquerdo


class _RoundRect:
    def __init__(self, r: int):
        self.r = r
        self.m = _corner_mask(r)

    def draw(self, img, x0, y0, x1, y1, color):
        h, w = img.shape[:2]
        x0, x1 = int(round(x0)), int(round(x1))
        y0, y1 = int(round(y0)), int(round(y1))
        r = min(self.r, (x1 - x0) // 2, (y1 - y0) // 2)
        if r < 2:
            _mix(img, y0, y1, x0, x1, color)
            return
        _mix(img, y0 + r, y1 - r, x0, x1, color)
        _mix(img, y0, y0 + r, x0 + r, x1 - r, color)
        _mix(img, y1 - r, y1, x0 + r, x1 - r, color)
        m = self.m if r == self.r else _corner_mask(r)
        col = np.array(color, np.float32)
        for (cy, cx, mk) in ((y0, x0, m), (y0, x1 - r, m[:, ::-1]),
                             (y1 - r, x0, m[::-1, :]), (y1 - r, x1 - r, m[::-1, ::-1])):
            ya, yb, xa, xb = max(0, cy), min(h, cy + r), max(0, cx), min(w, cx + r)
            if yb <= ya or xb <= xa:
                continue
            mm = mk[ya - cy:yb - cy, xa - cx:xb - cx, None]
            reg = img[ya:yb, xa:xb].astype(np.float32)
            img[ya:yb, xa:xb] = (reg * (1 - mm) + col * mm).astype(np.uint8)


def _shade(c, f):
    return tuple(int(max(0, min(255, v * f))) for v in c)


class Renderer:
    def __init__(self, notes: list[Note], s: Settings, offset: float):
        self.s = s
        self.offset = offset
        W, H = s.width, s.height
        kb_h = int(H * 0.17)
        self.kb_top = H - kb_h
        self.kb = Keyboard(W, self.kb_top, kb_h)
        self.pps = self.kb_top / s.fall_seconds  # pixels por segundo
        self.notes = sorted(notes, key=lambda n: n.start)
        self.starts = np.array([n.start + offset for n in self.notes])
        self.max_len = max((n.end - n.start for n in self.notes), default=0)
        self.rr = _RoundRect(max(3, int(self.kb.white_w * 0.22)))
        self.bg = self._background()

    def _color(self, n: Note):
        return self.s.left_color if n.pitch < self.s.split_note else self.s.right_color

    def _background(self):
        W, H, s = self.s.width, self.s.height, self.s
        img = np.empty((H, W, 3), np.uint8)
        grad = np.linspace(1.0, 0.65, self.kb_top)[:, None]
        img[:self.kb_top] = (np.array(s.background, np.float32)[None, None, :] * grad[:, :, None] + 4).astype(np.uint8)
        # linhas guia nas notas Dó e Fá
        for p in range(21, 109):
            if p % 12 in (0, 5):
                x = int(self.kb.x0[p])
                _mix(img, 0, self.kb_top, x, x + 1, _shade(s.background, 1.9))
        img[self.kb_top:] = 0
        return img

    def _draw_keyboard(self, img, active: dict[int, tuple]):
        kb, W, H = self.kb, self.s.width, self.s.height
        top = self.kb_top
        bottom = H
        gap = max(1, int(kb.white_w * 0.06))
        # teclas brancas
        for p in range(21, 109):
            if _is_black(p):
                continue
            col = active.get(p)
            base = (238, 238, 238) if col is None else col
            _mix(img, top, bottom, kb.x0[p] + gap / 2, kb.x1[p] - gap / 2, base)
            # leve sombreamento inferior
            _mix(img, bottom - int((bottom - top) * 0.05), bottom,
                 kb.x0[p] + gap / 2, kb.x1[p] - gap / 2, _shade(base, 0.8))
        # sombra do teclado
        _mix(img, top, top + max(2, int(H * 0.006)), 0, W, (0, 0, 0), 0.45)
        # teclas pretas
        bh = int((bottom - top) * 0.62)
        for p in range(21, 109):
            if not _is_black(p):
                continue
            col = active.get(p)
            base = (25, 25, 28) if col is None else _shade(col, 0.85)
            _mix(img, top, top + bh, kb.x0[p], kb.x1[p], base)
            hl = (70, 70, 76) if col is None else _shade(col, 1.15)
            inset = max(1, int((kb.x1[p] - kb.x0[p]) * 0.15))
            _mix(img, top + bh - int(bh * 0.08), top + bh, kb.x0[p] + inset, kb.x1[p] - inset, hl)
        # faixa colorida (feltro vermelho) acima do teclado
        _mix(img, top - max(2, int(H * 0.004)), top, 0, W, (150, 20, 30))

    def frame(self, t: float) -> np.ndarray:
        img = self.bg.copy()
        kb_top = self.kb_top
        horizon = t + self.s.fall_seconds
        i0 = np.searchsorted(self.starts, t - self.max_len - 0.1)
        i1 = np.searchsorted(self.starts, horizon + 0.01)
        active: dict[int, tuple] = {}
        visible = self.notes[i0:i1]
        # brancas primeiro, pretas por cima
        visible = sorted(visible, key=lambda n: _is_black(n.pitch))
        pad = max(1, int(self.kb.white_w * 0.06))
        for n in visible:
            st, en = n.start + self.offset, n.end + self.offset
            if en < t:
                continue
            y_bot = kb_top - (st - t) * self.pps
            y_top = kb_top - (en - t) * self.pps
            y_bot = min(y_bot, kb_top)
            if y_bot - y_top < 3:
                y_top = y_bot - 3
            col = self._color(n)
            if _is_black(n.pitch):
                col = _shade(col, 0.72)
            x0, x1 = self.kb.x0[n.pitch] + pad, self.kb.x1[n.pitch] - pad
            # borda clara + corpo
            self.rr.draw(img, x0, y_top, x1, y_bot, _shade(col, 1.35))
            self.rr.draw(img, x0 + 2, y_top + 2, x1 - 2, y_bot - 2, col)
            if st <= t <= en:
                active[n.pitch] = col
        # brilho nas teclas tocando
        for p, col in active.items():
            gh = int(self.s.height * 0.035)
            for k in range(gh):
                a = 0.35 * (1 - k / gh) ** 2
                _mix(img, kb_top - k - 1, kb_top - k, self.kb.x0[p] - 3, self.kb.x1[p] + 3,
                     _shade(col, 1.5), a)
        self._draw_keyboard(img, active)
        return img


# --------------------------------------------------------------------------- #
# Pipeline completo
# --------------------------------------------------------------------------- #

def make_video(audio_path: str, out_path: str, s: Settings | None = None,
               progress=lambda f, msg: None, cancel=lambda: False) -> str:
    s = s or Settings()

    # pesos aproximados de cada etapa na barra de progresso
    def stage(a, b):
        return lambda f, msg: progress(a + (b - a) * f, msg)

    notes = transcribe(audio_path, stage(0.0, 0.40))
    if not notes:
        raise RuntimeError("Nenhuma nota de piano foi detectada nesse áudio.")
    if s.save_midi:
        write_midi(notes, os.path.splitext(out_path)[0] + ".mid")

    last = max(n.sound_end for n in notes)
    duration = s.lead_in + last + s.tail
    audio = synthesize(notes, duration, s.lead_in, stage(0.40, 0.45))

    tmpdir = tempfile.mkdtemp(prefix="pianovideo_")
    wav_path = os.path.join(tmpdir, "recriado.wav")
    write_wav(wav_path, audio)

    rend = Renderer(notes, s, s.lead_in)
    total = int(duration * s.fps)
    cmd = [ffmpeg_exe(), "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{s.width}x{s.height}",
           "-r", str(s.fps), "-i", "-",
           "-i", wav_path,
           "-c:v", "libx264", "-preset", "medium", "-crf", str(s.crf),
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-shortest", "-movflags", "+faststart", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW)
    p = stage(0.45, 1.0)
    try:
        for i in range(total):
            if cancel():
                raise RuntimeError("Cancelado.")
            proc.stdin.write(rend.frame(i / s.fps).tobytes())
            if i % s.fps == 0:
                p(i / total, f"Gerando vídeo... {i // s.fps}s / {int(duration)}s")
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="ignore")
        if proc.wait() != 0:
            raise RuntimeError("Erro no ffmpeg: " + err)
    except BaseException:
        proc.kill()
        raise
    finally:
        try:
            os.remove(wav_path)
            os.rmdir(tmpdir)
        except OSError:
            pass
    progress(1.0, f"Pronto! {len(notes)} notas. Vídeo salvo em: {out_path}")
    return out_path
