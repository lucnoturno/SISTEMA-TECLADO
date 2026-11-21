"""Baixa o modelo de IA e as amostras de piano (só precisa rodar uma vez, antes de compilar)."""
import os
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
SAMPLES = "https://tonejs.github.io/audio/salamander/{}.mp3"


def get(url, path, min_size=1):
    if os.path.exists(path) and os.path.getsize(path) >= min_size:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print("Baixando", os.path.basename(path), "...")
    urllib.request.urlretrieve(url, path + ".part")
    os.replace(path + ".part", path)


get(MODEL, os.path.join(ROOT, "models", "piano_model.pth"), int(1.6e8))
names = ["A0"] + [f"{n}{o}" for o in range(1, 8) for n in ("C", "Ds", "Fs", "A")] + ["C8"]
for n in names:
    get(SAMPLES.format(n), os.path.join(ROOT, "samples", n + ".mp3"))
print("OK")
