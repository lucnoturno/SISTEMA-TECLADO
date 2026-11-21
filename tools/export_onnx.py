"""Converte o modelo PyTorch para ONNX (usado no app Android)."""
import sys, numpy as np, torch
from piano_transcription_inference.models import Note_pedal
out = sys.argv[1]
m = Note_pedal(frames_per_second=100, classes_num=88)
ck = torch.load("models/piano_model.pth", map_location="cpu")
m.load_state_dict(ck["model"], strict=False); m.eval()
KEYS = ["reg_onset_output", "reg_offset_output", "frame_output", "velocity_output",
        "reg_pedal_onset_output", "reg_pedal_offset_output", "pedal_frame_output"]
class W(torch.nn.Module):
    def __init__(s, m): super().__init__(); s.m = m
    def forward(s, x):
        d = s.m(x); return tuple(d[k] for k in KEYS)
w = W(m)
x = torch.randn(1, 160000) * 0.1
with torch.no_grad(): ref = w(x)
torch.onnx.export(w, (x,), out, input_names=["audio"], output_names=KEYS, opset_version=17, dynamo=False)
import onnxruntime as ort
s = ort.InferenceSession(out)
res = s.run(None, {"audio": x.numpy()})
for k, a, b in zip(KEYS, ref, res): print(k, a.shape, float(np.abs(a.numpy() - b).max()))
