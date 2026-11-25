# 我的无限电台

把 Notion 技术知识库自动做成个人播客。零成本：GitHub 公开仓库 + GitHub Actions + edge-tts + GitHub Pages。

## 怎么运作

1. 你的 Claude 运行 `notion-podcast` 技能：扫描 Notion，挑选题、选体裁，把口播脚本写进 `episodes/<id>/episode.json`，提交推送。
2. 推送触发 GitHub Actions：用 edge-tts（云健 + 晓伊）逐句合成，拼接、响度归一、写入章节，把 MP3 上传为 Release 附件。
3. Actions 更新 `docs/feed.xml`（RSS）和 `docs/episodes.json`，GitHub Pages 对外提供：
   - 网页播放器：`https://<你的用户名>.github.io/<仓库名>/`，连续播放、跳章节、记住进度，可“添加到主屏幕”。
   - RSS：`https://<你的用户名>.github.io/<仓库名>/feed.xml`，可在 Apple Podcasts、Pocket Casts、AntennaPod 等 App 里按链接订阅。

## 一次性设置

1. 新建一个**公开**仓库（免费账户的私有仓库不能用 Pages，且播客 App 拿不到私有 Release 里的音频）。
2. 把本目录的文件推上去。
3. 改 `podcast.json` 里的 `repo` 和 `site_url`。
4. 仓库 Settings → Pages：Source 选 “Deploy from a branch”，分支 `main`，目录 `/docs`。
5. 仓库 Settings → Actions → General → Workflow permissions：选 “Read and write permissions”。

## 本地测试

```bash
pip install edge-tts mutagen   # 另需 ffmpeg
python tools/render.py --tts dummy   # 不联网，用静音跑通整个流程
python tools/render.py               # 用 edge-tts 真实合成到 build/
```

## 目录

- `podcast.json`：节目信息、Notion 根页面、音色。
- `episodes/<id>/episode.json`：每集脚本（章节 + 台词）。
- `state/notion-index.json`：技能维护的 Notion 扫描状态和体裁轮换记录。
- `tools/render.py`：合成与发布脚本。
- `docs/`：Pages 站点（播放器、RSS、章节 JSON）。
- `skill/SKILL.md`：技能说明的副本。

## 注意

- edge-tts 是微软 Edge 朗读接口的非官方调用，免费但没有服务保证。偶尔被限流时脚本会重试；如果 Actions 里长期失败，可在本地运行 `python tools/render.py --publish`。
- 仓库公开，意味着脚本和音频任何人都能访问。
