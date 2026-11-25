# 在 Kaggle 免费 GPU 上运行：用 Qwen3-TTS 逐句合成，打包成 out.tar。由 tools/kaggle_job.py 生成并提交。
import base64, json, os, subprocess, sys, tarfile, time
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "qwen-tts"], check=True)
import torch, soundfile as sf
from qwen_tts import Qwen3TTSModel

JOBS = json.loads(base64.b64decode("__JOBS__").decode("utf-8"))
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "无", flush=True)
t0 = time.time()
model = Qwen3TTSModel.from_pretrained(JOBS["model"], device_map="cuda:0", dtype=torch.float32)
print(f"加载 {time.time() - t0:.0f} 秒", flush=True)
root = "/kaggle/working/out"
stats = []
for ep in JOBS["episodes"]:
    os.makedirs(f"{root}/{ep['id']}", exist_ok=True)
    t1, audio_s = time.time(), 0.0
    for i, t in enumerate(ep["turns"]):
        kw = dict(text=t["text"], language="Chinese", speaker=t["speaker"])
        if t.get("instruct"):
            kw["instruct"] = t["instruct"]
        wavs, sr = model.generate_custom_voice(**kw)
        sf.write(f"{root}/{ep['id']}/t{i:04d}.wav", wavs[0], sr)
        audio_s += len(wavs[0]) / sr
    line = f"{ep['id']}: 音频 {audio_s:.0f} 秒，合成 {time.time() - t1:.0f} 秒"
    print(line, flush=True)
    stats.append(line)
open(f"{root}/stats.txt", "w", encoding="utf-8").write("\n".join(stats) + "\n")
with tarfile.open("/kaggle/working/out.tar", "w") as tf:
    tf.add(root, arcname="out")
subprocess.run(["rm", "-rf", root])
