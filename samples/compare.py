"""面试官音色对比：用第一集的前两章，候选人固定 Brian，面试官换不同音色各渲染一版，并报每秒字数。"""
import asyncio, json, re, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import render

INTERVIEWERS = {
    "Ava": {"voice": "en-US-AvaMultilingualNeural", "rate": "+12%", "pitch": "-2Hz"},
    "Emma": {"voice": "en-US-EmmaMultilingualNeural", "rate": "+12%", "pitch": "-2Hz"},
    "Vivienne": {"voice": "fr-FR-VivienneMultilingualNeural", "rate": "+12%", "pitch": "-2Hz"},
    "Thalita": {"voice": "pt-BR-ThalitaMultilingualNeural", "rate": "+12%", "pitch": "-2Hz"},
    "晓伊": {"voice": "zh-CN-XiaoyiNeural", "rate": "+0%", "pitch": "-2Hz"},
}
base = json.loads((render.EPISODES_DIR / "2026-11-25-cache-eviction" / "episode.json").read_text(encoding="utf-8"))
out = Path("out"); out.mkdir(exist_ok=True)
for i, (name, v) in enumerate(INTERVIEWERS.items()):
    render.CONFIG["voices"]["B"] = dict(v, name=name)
    ep = dict(base, id=f"iv-{i}", chapters=base["chapters"][:2])
    mp3, total, _ = asyncio.run(render.render_episode(ep, "edge"))
    shutil.copy(mp3, out / f"iv-{i}.mp3")
    # 只有面试官的台词，用来量这个音色的语速
    solo = dict(base, id=f"ivs-{i}", chapters=[{"title": "x", "lines": [l for c in base["chapters"][:3] for l in c["lines"] if l["speaker"] == "B"]}])
    _, t2, _ = asyncio.run(render.render_episode(solo, "edge"))
    chars = sum(len(re.sub(r"[\W_]", "", l["text"])) for l in solo["chapters"][0]["lines"])
    print(f"{name}: 对话 {total:.1f} 秒；面试官独白 {chars / t2:.2f} 字/秒")
