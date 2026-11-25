"""在 CPU 上试 Qwen3-TTS：用第一集前两章做面试对话，量合成速度（RTF）。
用法：python samples/qwen/qwen_test.py <模型> <面试官> <候选人> <输出名> [instruct]"""
import json, subprocess, sys, time
from pathlib import Path
import numpy as np, soundfile as sf, torch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import render
from qwen_tts import Qwen3TTSModel

model_id, iv, cand, name = sys.argv[1:5]
instruct = sys.argv[5] if len(sys.argv) > 5 else None
torch.set_num_threads(4)
t0 = time.time()
model = Qwen3TTSModel.from_pretrained(model_id, device_map="cpu", dtype=torch.float32)
print(f"[{name}] 加载 {time.time() - t0:.0f} 秒", flush=True)

ep = json.loads((render.EPISODES_DIR / "2026-11-25-cache-eviction" / "episode.json").read_text(encoding="utf-8"))
ep["chapters"] = ep["chapters"][:2]
turns = render.merge_turns(ep)
spk = {"A": cand, "B": iv}
pieces, sr, synth, prev_ch = [], None, 0.0, None
for i, (ci, line) in enumerate(turns):
    t = time.time()
    kw = dict(text=line["text"], language="Chinese", speaker=spk[line["speaker"]])
    if instruct:
        kw["instruct"] = instruct
    wavs, sr = model.generate_custom_voice(**kw)
    synth += time.time() - t
    gap = 1.0 if (prev_ch is not None and ci != prev_ch) else float(line.get("gap", 0.3))
    if pieces:
        pieces.append(np.zeros(int(sr * gap), dtype=np.float32))
    pieces.append(np.asarray(wavs[0], dtype=np.float32))
    prev_ch = ci
    print(f"  {i + 1}/{len(turns)} {time.time() - t:.1f}s", flush=True)
audio = np.concatenate(pieces)
dur = len(audio) / sr
Path("out").mkdir(exist_ok=True)
sf.write(f"out/{name}.wav", audio, sr)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"out/{name}.wav", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ac", "1", "-b:a", "64k", f"out/{name}.mp3"], check=True)
Path(f"out/{name}.wav").unlink()
line = f"{name}: 音频 {dur:.1f} 秒，合成 {synth:.0f} 秒，RTF {synth / dur:.2f}（每秒音频要算 {synth / dur:.1f} 秒）"
print(line)
with open("out/stats.txt", "a", encoding="utf-8") as f:
    f.write(line + "\n")
