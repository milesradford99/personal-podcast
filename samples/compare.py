"""候选人音色对比：用第一集的前两章，面试官固定晓伊，候选人换不同音色各渲染一版。"""
import asyncio, json, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import render

CANDIDATES = {
    "云健": {"voice": "zh-CN-YunjianNeural", "rate": "+0%", "pitch": "-4Hz"},
    "云希": {"voice": "zh-CN-YunxiNeural", "rate": "+0%", "pitch": "-4Hz"},
    "Brian多语言": {"voice": "en-US-BrianMultilingualNeural", "rate": "+16%", "pitch": "-3Hz"},
    "Andrew多语言": {"voice": "en-US-AndrewMultilingualNeural", "rate": "+28%", "pitch": "-3Hz"},
}
ep = json.loads((render.EPISODES_DIR / "2026-11-25-cache-eviction" / "episode.json").read_text(encoding="utf-8"))
ep["chapters"] = ep["chapters"][:2]
out = Path("out"); out.mkdir(exist_ok=True)
for i, (name, v) in enumerate(CANDIDATES.items()):
    render.CONFIG["voices"]["A"] = dict(v, name=name)
    ep["id"] = f"compare-{i}"
    mp3, total, _ = asyncio.run(render.render_episode(ep, "edge"))
    shutil.copy(mp3, out / f"compare-{i}.mp3")
    print(name, round(total, 1), "秒")
