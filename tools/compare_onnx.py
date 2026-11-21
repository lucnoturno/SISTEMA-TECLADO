import sys, time, numpy as np, onnxruntime as ort
sys.path.insert(0, "app")
from pianovideo.core import decode_audio
from piano_transcription_inference.inference import PianoTranscription
from piano_transcription_inference.utilities import RegressionPostProcessor
KEYS=["reg_onset_output","reg_offset_output","frame_output","velocity_output","reg_pedal_onset_output","reg_pedal_offset_output","pedal_frame_output"]
audio = decode_audio(sys.argv[1], 16000)
pt = PianoTranscription.__new__(PianoTranscription); pt.segment_samples=160000
def run(path):
    s = ort.InferenceSession(path); a=audio[None]
    pad = int(np.ceil(a.shape[1]/160000))*160000 - a.shape[1]
    a = np.concatenate([a, np.zeros((1,pad),np.float32)],1)
    segs = pt.enframe(a, 160000).astype(np.float32)
    t=time.time(); outs={k:[] for k in KEYS}
    for seg in segs:
        r = s.run(None, {"audio": seg[None]})
        for k,v in zip(KEYS,r): outs[k].append(v)
    dt=time.time()-t
    d = {k: pt.deframe(np.concatenate(v,0)) for k,v in outs.items()}
    pp = RegressionPostProcessor(100,88,0.3,0.3,0.1,0.2)
    n,_ = pp.output_dict_to_midi_events(d)
    return sorted((round(float(e['onset_time']),2), e['midi_note']) for e in n), dt
a, ta = run(sys.argv[2]); b, tb = run(sys.argv[3])
print("fp32", len(a), "notas", round(ta,2),"s | int8", len(b), "notas", round(tb,2), "s")
sa=set((round(x,1),p) for x,p in a); sb=set((round(x,1),p) for x,p in b)
print("diferenças:", sa ^ sb)
