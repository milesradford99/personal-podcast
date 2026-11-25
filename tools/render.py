#!/usr/bin/env python3
"""把 episodes/<id>/episode.json 渲染成带章节的 MP3，并更新 RSS 与网页播放器数据。

用法：
  python tools/render.py                 # 渲染所有未发布的集，生成到 build/
  python tools/render.py --publish       # 渲染后上传到 GitHub Release，并更新 docs/
  python tools/render.py --tts dummy     # 不联网，用静音代替语音（测试管线用）

依赖：ffmpeg、edge-tts、mutagen；--publish 还需要 gh CLI（GitHub Actions 里自带）。
"""
import argparse
import asyncio
import email.utils
import json
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "podcast.json").read_text(encoding="utf-8"))
DOCS = ROOT / "docs"
BUILD = ROOT / "build"
EPISODES_DIR = ROOT / "episodes"
INDEX_FILE = DOCS / "episodes.json"
RATE = 24000
LINE_GAP = 0.3       # 换人说话前的停顿（每句的首尾静音已裁掉，这就是实际停顿）
SAME_SPK_GAP = 0.3   # 同一个人连续两句、且被拆开合成时
CHAPTER_GAP = 1.2
# 裁掉 edge-tts 每段自带的首尾静音，停顿才能精确控制（抢话、思考停顿才有效果）
TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def write_silence(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * int(RATE * seconds))


async def tts_edge(text, voice, rate, pitch, out_mp3):
    import edge_tts

    last = None
    for attempt in range(4):
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out_mp3))
            if out_mp3.stat().st_size > 0:
                return
        except Exception as e:  # 网络抖动或限流，退避重试
            last = e
        await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"edge-tts 失败：{last}")


async def synth_line(i, line, voices, tmp, backend, sem):
    spk = voices.get(line["speaker"]) or next(iter(voices.values()))
    wav = tmp / f"l{i:05d}.wav"
    if backend == "dummy":
        write_silence(wav, max(0.6, len(line["text"]) / 4.2))  # 约 4.2 字/秒
        return wav
    mp3 = tmp / f"l{i:05d}.mp3"
    async with sem:
        await tts_edge(line["text"], spk["voice"], line.get("rate") or spk.get("rate", "+0%"),
                       line.get("pitch") or spk.get("pitch", "+0Hz"), mp3)
    run(["ffmpeg", "-y", "-i", str(mp3), "-af", TRIM, "-ac", "1", "-ar", str(RATE), str(wav)])
    return wav


def merge_turns(ep):
    """同一个人连续说的几句，没有单独指定停顿和语速的，合成一次。
    edge-tts 一次读完一整段，句间语调是连贯的；逐句合成每句都像重新起调，听着像念稿。"""
    flat = []
    for ci, ch in enumerate(ep["chapters"]):
        for line in ch["lines"]:
            text = line.get("text", "").strip()
            if not text:
                continue
            prev = flat[-1] if flat else None
            if (prev and prev[0] == ci and prev[1]["speaker"] == line["speaker"]
                    and "gap" not in line and "rate" not in line and "pitch" not in line
                    and "rate" not in prev[1] and "pitch" not in prev[1]
                    and len(prev[1]["text"]) + len(text) <= 150):
                prev[1]["text"] += text
            else:
                flat.append((ci, dict(line, text=text)))
    return flat


def lint(ep):
    """朗读稿里容易读错的地方（只提醒，不拦）"""
    out = []
    for ch in ep["chapters"]:
        for line in ch["lines"]:
            t = line.get("text", "")
            for m in re.findall(r"(?<![A-Za-z])\d[\d.,%]*", t):
                out.append(f"阿拉伯数字「{m}」：{t[:20]}")
            for m in re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z0-9-])", t):
                out.append(f"单个字母「{m}」：{t[:20]}")
            if len(t) > 80:
                out.append(f"句子太长（{len(t)} 字）：{t[:20]}")
    return out


async def render_episode(ep, backend):
    voices = CONFIG["voices"]
    tmp = Path(tempfile.mkdtemp(prefix="ep-"))
    try:
        flat = merge_turns(ep)
        sem = asyncio.Semaphore(4)
        wavs = await asyncio.gather(*[
            synth_line(i, line, voices, tmp, backend, sem) for i, (_, line) in enumerate(flat)
        ])
        gaps = {}

        def gap_file(sec):
            sec = round(max(0.0, min(3.0, float(sec))), 2)
            if sec not in gaps:
                gaps[sec] = tmp / f"gap_{int(sec * 100)}.wav"
                write_silence(gaps[sec], sec)
            return gaps[sec]

        parts, starts, t, prev_ch, prev_spk = [], {}, 0.0, None, None
        for (ci, line), wav in zip(flat, wavs):
            if prev_ch is not None:
                if ci != prev_ch:
                    sec = CHAPTER_GAP
                elif "gap" in line:  # 脚本可指定停顿：抢话用 0.05，思考用 0.8
                    sec = line["gap"]
                else:
                    sec = SAME_SPK_GAP if line["speaker"] == prev_spk else LINE_GAP
                g = gap_file(sec)
                parts.append(g)
                t += wav_seconds(g)
            prev_spk = line["speaker"]
            if ci not in starts:
                starts[ci] = t
            parts.append(wav)
            t += wav_seconds(wav)
            prev_ch = ci
        total = t

        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        BUILD.mkdir(exist_ok=True)
        out = BUILD / f"{ep['id']}.mp3"
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1",
             "-b:a", "64k", str(out)])

        chapters = []
        ordered = sorted(starts.items())
        for n, (ci, st) in enumerate(ordered):
            end = ordered[n + 1][1] if n + 1 < len(ordered) else total
            chapters.append({"title": ep["chapters"][ci]["title"],
                             "startTime": round(st, 2), "endTime": round(end, 2)})
        embed_chapters(out, ep, chapters)
        return out, total, chapters
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def embed_chapters(mp3, ep, chapters):
    from mutagen.id3 import CHAP, CTOC, CTOCFlags, ID3, TALB, TIT2, TPE1, ID3NoHeaderError

    try:
        tags = ID3(str(mp3))
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=ep["title"]))
    tags.add(TALB(encoding=3, text=CONFIG["title"]))
    tags.add(TPE1(encoding=3, text=CONFIG["author"]))
    ids = []
    for i, c in enumerate(chapters):
        cid = f"ch{i}"
        ids.append(cid)
        tags.add(CHAP(element_id=cid, start_time=int(c["startTime"] * 1000),
                      end_time=int(c["endTime"] * 1000),
                      sub_frames=[TIT2(encoding=3, text=c["title"])]))
    tags.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                  child_element_ids=ids, sub_frames=[TIT2(encoding=3, text="目录")]))
    tags.save(str(mp3))


def load_index():
    return json.loads(INDEX_FILE.read_text(encoding="utf-8")) if INDEX_FILE.exists() else []


def save_index(items):
    INDEX_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish_release(ep, mp3):
    tag = f"ep-{ep['id']}"
    repo = CONFIG["repo"]
    exists = subprocess.run(["gh", "release", "view", tag, "--repo", repo],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if exists:
        run(["gh", "release", "upload", tag, str(mp3), "--clobber", "--repo", repo])
    else:
        run(["gh", "release", "create", tag, str(mp3), "--repo", repo,
             "--title", ep["title"], "--notes", ep.get("description", "")])
    return f"https://github.com/{repo}/releases/download/{tag}/{mp3.name}"


def build_feed(items):
    site = CONFIG["site_url"].rstrip("/") + "/"
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:podcast="https://podcastindex.org/namespace/1.0">',
        "<channel>",
        f"<title>{escape(CONFIG['title'])}</title>",
        f"<link>{escape(site)}</link>",
        f"<description>{escape(CONFIG['description'])}</description>",
        f"<language>{CONFIG.get('language', 'zh-cn')}</language>",
        f"<itunes:author>{escape(CONFIG['author'])}</itunes:author>",
        "<itunes:type>serial</itunes:type>",
        "<itunes:explicit>false</itunes:explicit>",
        f'<itunes:image href="{escape(site)}cover.png"/>',
    ]
    for n, it in enumerate(sorted(items, key=lambda x: x["seq"]), start=1):
        pub = email.utils.format_datetime(datetime.fromisoformat(it["published_at"]))
        d = int(it["duration"])
        out += [
            "<item>",
            f"<title>{escape(it['title'])}</title>",
            f"<description>{escape(it.get('description', ''))}</description>",
            f"<guid isPermaLink=\"false\">{escape(it['id'])}</guid>",
            f"<pubDate>{pub}</pubDate>",
            f'<enclosure url="{escape(it["url"])}" length="{it["bytes"]}" type="audio/mpeg"/>',
            f"<itunes:duration>{d // 3600:02d}:{d % 3600 // 60:02d}:{d % 60:02d}</itunes:duration>",
            f"<itunes:episode>{it['seq']}</itunes:episode>",
            "<itunes:episodeType>full</itunes:episodeType>",
            f'<podcast:chapters url="{escape(site)}chapters/{escape(it["id"])}.json" '
            'type="application/json+chapters"/>',
            "</item>",
        ]
    out += ["</channel>", "</rss>"]
    (DOCS / "feed.xml").write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--tts", choices=["edge", "dummy"], default="edge")
    ap.add_argument("--only", help="只渲染指定 id")
    ap.add_argument("--lint", action="store_true", help="只检查朗读稿，不渲染")
    args = ap.parse_args()

    if args.lint:
        n = 0
        for f in sorted(EPISODES_DIR.glob("*/episode.json")):
            ep = json.loads(f.read_text(encoding="utf-8"))
            if args.only and ep.get("id") != args.only:
                continue
            for w in lint(ep):
                print(f"{ep.get('id')}：{w}")
                n += 1
        print(f"共 {n} 处提醒")
        return

    index = load_index()
    done = {it["id"] for it in index}
    todo = []
    for f in sorted(EPISODES_DIR.glob("*/episode.json")):
        ep = json.loads(f.read_text(encoding="utf-8"))
        if not ID_RE.match(ep.get("id", "")):
            sys.exit(f"{f}: id 只能用小写字母、数字和连字符")
        if args.only and ep["id"] != args.only:
            continue
        if ep["id"] in done and not args.only:
            continue
        todo.append(ep)

    if not todo:
        print("没有待渲染的集。")
    for ep in todo:
        print(f"渲染 {ep['id']} …", flush=True)
        for w in lint(ep):
            print("  提醒：" + w)
        mp3, total, chapters = asyncio.run(render_episode(ep, args.tts))
        (DOCS / "chapters").mkdir(parents=True, exist_ok=True)
        (DOCS / "chapters" / f"{ep['id']}.json").write_text(
            json.dumps({"version": "1.2.0", "chapters": chapters}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        url = publish_release(ep, mp3) if args.publish else mp3.name
        prev = next((it for it in index if it["id"] == ep["id"]), None)
        index = [it for it in index if it["id"] != ep["id"]]
        seq = ep.get("seq") or (prev or {}).get("seq") or (max([i["seq"] for i in index], default=0) + 1)
        index.append({
            "id": ep["id"],
            "seq": seq,
            "title": ep["title"],
            "description": ep.get("description", ""),
            "format": ep.get("format", ""),
            "sources": ep.get("sources", []),
            "url": url,
            "bytes": mp3.stat().st_size,
            "duration": round(total, 1),
            "chapters": chapters,
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        index.sort(key=lambda x: x["seq"])
        save_index(index)
        print(f"  完成：{total / 60:.1f} 分钟，{len(chapters)} 章")
    build_feed(index)


if __name__ == "__main__":
    main()
