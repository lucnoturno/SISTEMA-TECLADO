"""PianoVideo - transforma uma gravação de piano (wav/mp3) em vídeo de notas caindo.

Uso com interface:   PianoVideo
Uso por linha de comando:   PianoVideo musica.mp3 [-o saida.mp4] [--fps 60] [--res 1080]
"""
import os
import sys

# Em apps sem console (Windows), stdout/stderr podem ser None.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440),
               "Vertical 1080x1920": (1080, 1920)}


def run_cli(argv):
    import argparse
    from pianovideo.core import Settings, make_video

    ap = argparse.ArgumentParser(description="Gera vídeo de piano com notas caindo.")
    ap.add_argument("audio")
    ap.add_argument("-o", "--output")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--res", default="1080p", choices=list(RESOLUTIONS))
    ap.add_argument("--speed", type=float, default=3.0,
                    help="segundos que a nota leva para cair (menor = mais rápido)")
    a = ap.parse_args(argv)
    out = a.output or os.path.splitext(a.audio)[0] + "_piano.mp4"
    w, h = RESOLUTIONS[a.res]
    s = Settings(width=w, height=h, fps=a.fps, fall_seconds=a.speed)

    def prog(f, msg):
        print(f"\r[{int(f * 100):3d}%] {msg}".ljust(80), end="", flush=True)

    make_video(a.audio, out, s, prog)
    print()


def run_gui():
    import threading
    import queue
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("PianoVideo - notas caindo")
    root.geometry("620x360")
    root.resizable(False, False)

    q = queue.Queue()
    state = {"cancel": False, "running": False}

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill="both", expand=True)

    in_var, out_var = tk.StringVar(), tk.StringVar()
    res_var, fps_var, speed_var = tk.StringVar(value="1080p"), tk.StringVar(value="60"), tk.DoubleVar(value=3.0)

    def pick_in():
        p = filedialog.askopenfilename(title="Escolha a música",
                                       filetypes=[("Áudio", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac"),
                                                  ("Todos", "*.*")])
        if p:
            in_var.set(p)
            out_var.set(os.path.splitext(p)[0] + "_piano.mp4")

    def pick_out():
        p = filedialog.asksaveasfilename(title="Salvar vídeo como", defaultextension=".mp4",
                                         filetypes=[("Vídeo MP4", "*.mp4")])
        if p:
            out_var.set(p)

    ttk.Label(frm, text="Música (wav/mp3):").grid(row=0, column=0, sticky="w")
    ttk.Entry(frm, textvariable=in_var, width=52).grid(row=1, column=0, columnspan=3, sticky="we")
    ttk.Button(frm, text="Escolher...", command=pick_in).grid(row=1, column=3, padx=(6, 0))

    ttk.Label(frm, text="Salvar vídeo em:").grid(row=2, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(frm, textvariable=out_var, width=52).grid(row=3, column=0, columnspan=3, sticky="we")
    ttk.Button(frm, text="Alterar...", command=pick_out).grid(row=3, column=3, padx=(6, 0))

    opts = ttk.Frame(frm)
    opts.grid(row=4, column=0, columnspan=4, sticky="w", pady=(14, 0))
    ttk.Label(opts, text="Resolução:").pack(side="left")
    ttk.Combobox(opts, textvariable=res_var, values=list(RESOLUTIONS), width=17,
                 state="readonly").pack(side="left", padx=(4, 14))
    ttk.Label(opts, text="FPS:").pack(side="left")
    ttk.Combobox(opts, textvariable=fps_var, values=["30", "60"], width=4,
                 state="readonly").pack(side="left", padx=(4, 14))
    ttk.Label(opts, text="Queda (s):").pack(side="left")
    ttk.Spinbox(opts, textvariable=speed_var, from_=1.0, to=8.0, increment=0.5,
                width=5).pack(side="left", padx=4)

    bar = ttk.Progressbar(frm, length=580, maximum=1000)
    bar.grid(row=5, column=0, columnspan=4, pady=(22, 4), sticky="we")
    status = ttk.Label(frm, text="Escolha uma música para começar.", wraplength=580)
    status.grid(row=6, column=0, columnspan=4, sticky="w")

    btns = ttk.Frame(frm)
    btns.grid(row=7, column=0, columnspan=4, pady=(18, 0))
    go_btn = ttk.Button(btns, text="Gerar vídeo")
    cancel_btn = ttk.Button(btns, text="Cancelar", state="disabled")
    open_btn = ttk.Button(btns, text="Abrir pasta", state="disabled")
    go_btn.pack(side="left", padx=4)
    cancel_btn.pack(side="left", padx=4)
    open_btn.pack(side="left", padx=4)

    def worker(inp, out, s):
        from pianovideo.core import make_video
        try:
            make_video(inp, out, s, lambda f, m: q.put(("p", f, m)), lambda: state["cancel"])
            q.put(("done", out))
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            q.put(("err", str(e)))

    def start():
        inp, out = in_var.get().strip(), out_var.get().strip()
        if not os.path.isfile(inp):
            messagebox.showerror("PianoVideo", "Escolha um arquivo de áudio válido.")
            return
        if not out:
            out = os.path.splitext(inp)[0] + "_piano.mp4"
            out_var.set(out)
        from pianovideo.core import Settings
        w, h = RESOLUTIONS[res_var.get()]
        try:
            speed = float(speed_var.get())
        except (tk.TclError, ValueError):
            speed = 3.0
        s = Settings(width=w, height=h, fps=int(fps_var.get()), fall_seconds=speed)
        state.update(cancel=False, running=True)
        go_btn.config(state="disabled")
        cancel_btn.config(state="normal")
        open_btn.config(state="disabled")
        bar["value"] = 0
        status.config(text="Iniciando... (a primeira etapa pode levar alguns minutos)")
        threading.Thread(target=worker, args=(inp, out, s), daemon=True).start()

    def cancel():
        state["cancel"] = True
        status.config(text="Cancelando...")

    def open_folder():
        folder = os.path.dirname(out_var.get())
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", folder])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder])

    go_btn.config(command=start)
    cancel_btn.config(command=cancel)
    open_btn.config(command=open_folder)

    def poll():
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == "p":
                    bar["value"] = msg[1] * 1000
                    status.config(text=msg[2])
                else:
                    state["running"] = False
                    go_btn.config(state="normal")
                    cancel_btn.config(state="disabled")
                    if msg[0] == "done":
                        bar["value"] = 1000
                        status.config(text="Pronto! Vídeo salvo em:\n" + msg[1])
                        open_btn.config(state="normal")
                    else:
                        status.config(text="Erro: " + msg[1])
                        if msg[1] != "Cancelado.":
                            messagebox.showerror("PianoVideo", msg[1])
        except queue.Empty:
            pass
        root.after(100, poll)

    poll()
    root.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    args = [a for a in sys.argv[1:] if not a.startswith("-psn")]  # macOS Finder arg
    if args:
        run_cli(args)
    else:
        run_gui()
