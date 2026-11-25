#!/usr/bin/env python3
"""把待渲染的集交给 Kaggle 免费 GPU 用 Qwen3-TTS 合成，等它跑完，把逐句音频取回到 build/qwen/。
在 GitHub Actions 里运行，需要环境变量 KAGGLE_USERNAME、KAGGLE_KEY。
用法：python tools/kaggle_job.py            # 合成所有未发布的集
      python tools/kaggle_job.py --samples  # 合成音色对比样本（第一集前两章，多种搭配）"""
import argparse, base64, json, os, subprocess, sys, tarfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render

ROOT = render.ROOT
QW = render.CONFIG["qwen"]
SAMPLE_PAIRS = [("Vivian", "Uncle_Fu"), ("Serena", "Uncle_Fu"), ("Vivian", "Dylan"), ("Serena", "Aiden"), ("Vivian", "Ryan")]


def turns_for(ep, voices):
    out = []
    for _, line in render.merge_turns(ep):
        v = voices[line["speaker"]]
        out.append({"text": line["text"], "speaker": v["speaker"], "instruct": v.get("instruct")})
    return out


def sample_episodes():
    base = json.loads((render.EPISODES_DIR / "2026-11-25-cache-eviction" / "episode.json").read_text(encoding="utf-8"))
    eps = []
    for iv, cand in SAMPLE_PAIRS:
        ep = dict(base, id=f"s-{iv.lower()}-{cand.lower().replace('_', '')}", chapters=base["chapters"][:2])
        voices = {"A": dict(QW["voices"]["A"], speaker=cand), "B": dict(QW["voices"]["B"], speaker=iv)}
        eps.append((ep, voices))
    return eps


def pending_episodes():
    done = {it["id"] for it in render.load_index()}
    eps = []
    for f in sorted(render.EPISODES_DIR.glob("*/episode.json")):
        ep = json.loads(f.read_text(encoding="utf-8"))
        if ep["id"] not in done:
            eps.append((ep, QW["voices"]))
    return eps


def kaggle(*args, check=True):
    r = subprocess.run(["kaggle", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"kaggle {' '.join(args)} 失败：{r.stderr or r.stdout}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", action="store_true")
    args = ap.parse_args()
    eps = sample_episodes() if args.samples else pending_episodes()
    if not eps:
        print("没有待合成的集。")
        return
    jobs = {"model": QW["model"], "episodes": [{"id": ep["id"], "turns": turns_for(ep, v)} for ep, v in eps]}
    user = os.environ["KAGGLE_USERNAME"]
    slug = f"{user}/podcast-qwen-tts"
    kdir = ROOT / "build" / "kaggle"
    kdir.mkdir(parents=True, exist_ok=True)
    code = (Path(__file__).parent / "kaggle" / "synth_template.py").read_text(encoding="utf-8")
    payload = base64.b64encode(json.dumps(jobs, ensure_ascii=False).encode("utf-8")).decode()
    (kdir / "synth.py").write_text(code.replace("__JOBS__", payload), encoding="utf-8")
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": slug, "title": "podcast-qwen-tts", "code_file": "synth.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": [],
    }), encoding="utf-8")
    print(kaggle("kernels", "push", "-p", str(kdir)))
    time.sleep(30)
    deadline = time.time() + 5 * 3600
    while True:
        st = kaggle("kernels", "status", slug, check=False).strip()
        print(time.strftime("%H:%M"), st, flush=True)
        low = st.lower()
        if "complete" in low:
            break
        if "error" in low or "cancel" in low:
            out = ROOT / "build" / "kaggle-log"
            kaggle("kernels", "output", slug, "-p", str(out), check=False)
            for p in out.glob("*.log"):
                print(p.read_text(errors="ignore")[-4000:])
            sys.exit("Kaggle 运行失败")
        if time.time() > deadline:
            sys.exit("Kaggle 超时")
        time.sleep(60)
    dl = ROOT / "build" / "kaggle-out"
    kaggle("kernels", "output", slug, "-p", str(dl))
    with tarfile.open(dl / "out.tar") as tf:
        tf.extractall(ROOT / "build" / "qwen")
    print((ROOT / "build" / "qwen" / "out" / "stats.txt").read_text(encoding="utf-8"))
    if args.samples:
        import asyncio, shutil
        (ROOT / "out").mkdir(exist_ok=True)
        for ep, _ in eps:
            mp3, total, _ = asyncio.run(render.render_episode(ep, "files"))
            shutil.copy(mp3, ROOT / "out" / f"{ep['id']}.mp3")
            print(ep["id"], f"{total:.0f} 秒")


if __name__ == "__main__":
    main()
