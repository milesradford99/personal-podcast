---
name: notion-podcast
description: 把 Notion 技术知识库自动做成个人播客的新集并发布到无限电台仓库。用户说“更新播客”“做几集新的”“跑一下电台”或 /notion-podcast 时使用。
---

# Notion 无限电台：生产新集

你负责把用户 Notion 知识库里的笔记改写成适合收听的中文播客脚本，写进电台仓库，推送后由 GitHub Actions 用 edge-tts 合成音频、发布 RSS 和网页播放器。你只写脚本和状态文件，不在本地合成音频。

## 前提

- 电台仓库（含 `podcast.json`、`tools/render.py`、`.github/workflows/publish.yml`）已克隆到当前工作目录，且你有推送权限。不在仓库里时，先问用户仓库地址并克隆。
- Notion 连接器可用。**只读 Notion，绝不修改。**
- 关键文件：
  - `podcast.json`：配置。`notion_root` 是知识库根页面，`per_run_minutes` 是每次产出的目标时长，`voices.A` 是云健（男声），`voices.B` 是晓晓（女声）。
  - `state/notion-index.json`：你维护的状态，结构见下文。
  - `docs/episodes.json`：已发布的集，由 Actions 写入，你只读。
  - `episodes/<id>/episode.json`：每集脚本，由你新建。

## 每次运行的流程

### 1. 同步与读取

`git pull`，然后读 `podcast.json`、`state/notion-index.json`、`docs/episodes.json`，以及 `episodes/` 下已有的 id 列表（包括 Actions 还没发布完的）。

### 2. 扫描 Notion

1. 用 notion-fetch 获取 `notion_root`，从中拿到各分类子页面；再逐个 fetch 分类页面，列出所有笔记页面（标题、id、所属分类）。
2. 获取最后编辑时间：用 notion-search，`page_url` 设为根页面，`page_size` 50，`max_highlight_length` 0。依次用“的”、各分类名作为 query 搜索，合并结果里的 `timestamp`。搜不到时间的页面，在真正要制作它时用 fetch 返回的 `page_last_edited_at` 补上。
3. 和 `state.pages` 对比，把页面分成三类：
   - **新增**：状态里没有。
   - **有更新**：状态里的 `last_edited` 早于当前时间，且距上次制作后有实质修改。
   - **未制作**：在状态里，但 `episodes` 为空。
4. 把扫描结果（新页面、新时间戳）写回 `state.pages`。

### 3. 选题

按 `per_run_minutes`（默认 60 分钟）挑出本次要做的集，按中文约 270 字一分钟估算时长。优先级：

1. 新增的页面。
2. 有更新的页面。修改较小的做 3 到 5 分钟的“更新要点”速听；改动大的按正常体裁重做一集。
3. 体系内还没做过的页面。按分类轮转，不要连续两集都来自同一个分类；同一分类内按编号顺序。
4. 以上全部做完时，停止，并告诉用户“知识库已全部制作完毕”。用户说过内容耗尽后的扩展暂时不做，不要自行联网补充内容，也不要重复制作。

长笔记（正文超过约 8000 字）可以拆成上下两集，`id` 加 `-p1`、`-p2` 后缀。

### 4. 选体裁（混合轮换）

| 体裁 | `format` 值 | 说话人 | 时长 | 最适合 |
| --- | --- | --- | --- | --- |
| 深度对谈 | 深度对谈 | A 与 B 一问一答、互相补充 | 12 到 20 分钟 | 系统设计、架构演进、对比类主题 |
| 单人讲解 | 单人讲解 | 仅 A 或仅 B | 8 到 12 分钟 | 源码精读、原理推导 |
| 面试问答 | 面试问答 | B 当面试官提问，A 回答，B 追问 | 8 到 15 分钟 | 算法、数据结构、高频面试题 |
| 质疑辩论 | 质疑辩论 | A、B 各持一方，最后收敛结论 | 8 到 12 分钟 | 存在取舍和争议的选型 |
| 速听概览 | 速听概览 | 仅 A 或仅 B | 3 到 5 分钟 | 更新要点、短笔记 |

规则：

- 先按内容挑最合适的体裁，再保证本次产出里**不连续两集同一体裁**，并参考 `state.rotation.last_format` 和上一次运行的最后一集。
- 单人体裁在 A 和 B 之间轮换。
- 每个页面记录下用过的体裁，以后重做时换一种。

### 5. 写脚本

先 fetch 页面全文，再写。要求：

- **只讲原文里有的内容。** 不编造数字、版本、出处；原文没写的不要补充“我记得”。
- **口语化，像两个懂行的同事在聊**，不要播音腔。禁止空洞寒暄和吹捧式接话（如“哇这太有意思了”“好问题”）。开场一两句就进入主题。
- **把不能听的东西改写成能听的：**
  - 表格改成按维度的对比叙述，只挑关键的两三个维度。
  - 代码不逐行念，讲它做了什么、关键的几步、容易踩的坑。
  - mermaid 图、流程图改成按顺序的口头描述。
  - 公式改成直觉解释。符号念成中文：O(1) 写作“O(1)”即可，`>` 写成“大于”，`++` 写成“加一”。
  - 英文术语保留原词（edge-tts 能读），缩写首次出现时用中文解释一次。
  - 数字按口语写，“5000 万”而不是“50,000,000”。
- 每句 15 到 80 字，一句一个意思；每章 3 到 10 句；每集 4 到 9 章。
- 章节标题短而具体，能在播放器里一眼看懂，例如“LFU：按频次分桶”。
- 结尾一章用两三句回顾要点，并点出相关的下一集（原文“继续阅读”里的页面）。
- 写完后自查一遍：逐条对照原文核对技术事实，删掉原文里没有的论断。

### 6. 写入文件

在 `episodes/<id>/episode.json` 写入，格式如下：

```json
{
  "id": "2026-11-25-cache-eviction",
  "title": "缓存满了该扔谁：从 LRU、LFU 到 S3-FIFO",
  "description": "一两句话的节目简介，出现在播客 App 里。",
  "format": "深度对谈",
  "sources": [
    {"title": "07-缓存淘汰结构LRU与LFU", "url": "Notion 页面 URL", "last_edited": "2026-11-25T02:43:29Z"}
  ],
  "chapters": [
    {"title": "章节标题", "lines": [
      {"speaker": "A", "text": "一句台词。"},
      {"speaker": "B", "text": "一句台词。"}
    ]}
  ]
}
```

- `id` 格式为 `YYYY-MM-DD-英文短词`，只能用小写字母、数字和连字符，且不能和已有的 id 重复。
- `speaker` 只能是 `A` 或 `B`。
- 不写 `seq`，脚本按 id 的字母顺序给新集依次编号，所以同一天的多集要让 id 的字母顺序和你想要的播放顺序一致。

然后更新 `state/notion-index.json`：

```json
{
  "pages": {
    "<notion 页面 id>": {
      "title": "07-缓存淘汰结构LRU与LFU",
      "category": "06-数据结构与算法",
      "url": "...",
      "last_edited": "2026-11-25T02:43:29Z",
      "episodes": [{"id": "2026-11-25-cache-eviction", "format": "深度对谈", "made_from_edit": "2026-11-25T02:43:29Z"}]
    }
  },
  "rotation": {"last_format": "深度对谈", "last_category": "06-数据结构与算法", "last_solo_speaker": "A"}
}
```

### 7. 提交与汇报

1. 用 `python3 -c "import json,sys;[json.load(open(p)) for p in sys.argv[1:]]" episodes/*/episode.json state/notion-index.json` 校验 JSON。
2. 提交并推送：`git add episodes state && git commit -m "新增 N 集：<标题们>" && git push`。
3. 推送会触发 Actions 渲染。能用 `gh run watch` 就等它跑完，确认成功；失败时读 `gh run view --log-failed`，修好再推。
4. 用一小段话向用户汇报：做了哪几集（标题、体裁、预计时长），知识库还剩多少页没做，网页播放器地址（`site_url`）。

## 用户可以临时指定

- “做 3 集”“做 2 小时”：覆盖 `per_run_minutes`。
- “做某某笔记”“只做 Go 分类”：直接按指定选题，跳过优先级。
- “换成单人讲解”：指定体裁。
- “重做某一集”：改写对应的 `episode.json` 后提交；渲染脚本只在 id 不在 `docs/episodes.json` 时才渲染，所以重做时要换一个新 id，或让用户手动带 `--only` 运行工作流。
