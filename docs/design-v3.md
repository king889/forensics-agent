# 设计 v3：逐题驱动 + 子 agent 取数

> 状态：**待确认**。确认后按「实施顺序」动代码。
> 上一版的失败见 §0，本节就是针对它设计的。

## 0. 为什么要重做

`$CASES_ROOT/test` 那场会话，68 分钟 168 条命令，只提交 1 道答案（还是更早会话做的）：

| 现象 | 数据 |
|---|---|
| 42 分钟卡在 `npm install realm` | 占总时长 62%，与取证无关 |
| `fcase note` / `fcase answer` | **0 次 / 0 次** |
| 压缩 3 次（20:04 / 20:55 / 21:03） | 每次 112k tokens，压缩后全部重挖 |
| 检材覆盖 | CHAN 94 条、FUNG 29 条、LEUNG 8 条、U 盘/Android/pcap **0 条** |
| 最大单条输出 | 50KB（撞 bash 上限） |

根因三条：**98 题一次全塞（没有目标）**、**命令无界（卡死 42 分钟）**、**线索不落盘（压缩即失忆）**。

## 1. 四个已定决策

| 决策 | 选择 | 理由 |
|---|---|---|
| case 粒度 | **一个 case 装 98 题** | 检材共享，索引只扫一次 |
| subagent | **用 Pi 自带 example**（`subagent` 工具 + agent md） | 现成、独立进程、支持并行/链式 |
| 顺序 | **先易后难**（U 盘 776M → pcap 318B → zip → 手机 → Android 29.8G） | 同样 1 分/题，先拿便宜的 |
| 装包 | **一律拦截，暂停请示** | agent 不自己装；`npm install realm` 那 42 分钟不能再发生 |

## 2. 单位

| 层 | 是什么 | 数量 |
|---|---|---|
| Case | 一批检材 | 1 |
| Question | 最小工作单元 | 98 |
| Session | **一道题一个 pi 进程** | ≤98 |
| Subagent | 一个检材上的取数工人 | 每题 0–3 |

## 3. 目录

```
<case>/
  evi/                  原始检材（555）
  work/                 中间产物
  meta/
    questions.json      98 题结构化
    evidence.db         findings / answers / deadends / pending_installs
    index/<artifact>.json   检材索引（脚本生成，不耗 token）
    briefs/Q07.md       每题作战简报（进上下文的第一份文件）
    sub/Q07-<art>.json  subagent 返回的结构化结果
    cmdlog.jsonl        每条命令的审计日志（guard 自动写）
    pending-install.md  待人工安装清单
```

## 4. 五个机制

### L1 逐题驱动

```bash
fcase import meta/question.md      # 解析 → questions.json（--dry-run 先看）
fcase board                        # 98 题看板：todo/doing/done/blocked
fcase next                         # 下一题（先易后难）
solve Q07                          # 起一个只含这道题的会话
```

`solve` 只注入四样，别的都不给：

1. `prompts/question.md` —— 短规约（约 40 行，不是全量 `agent.md`）
2. **只加载相关技能**（Q07 是 iOS 备份 → 只带 `mobile`）
3. `meta/briefs/Q07.md` —— 题干 + 已有线索 + 死路 + 索引摘要
4. 退出条件：**`fcase answer Q07` 未调用 → 不算完成**

### L2 上下文预算：`guard.ts` 覆盖内置 bash

Pi 支持扩展注册同名工具替换内置工具（`docs/extensions.md:2360`，渲染器自动继承）。所以**不靠模型自觉**，在工具层强制：

| 规则 | 行为 |
|---|---|
| 输出 > 8KB | 全量写 `work/out/<ts>.txt`，只回前 60 行 + 路径 |
| 命令 > 180s | SIGKILL，返回超时提示 |
| 安装命令 | `npm i/add`、`pip install`、`uv pip install`、`apt install`、`dpkg -i`、`install.sh` → **拒绝执行** + 写 `pending-install.md` |
| 写 `evi/` | 拒绝（555 之外再加一层） |
| 每条命令 | append `cmdlog.jsonl`：`{ts,cwd,cmd,exit,ms,out_bytes,out_path}` |
| 每 10 条 | 输出尾部插一行：`[guard] 12 条命令，上次 fcase note 在 40 分钟前` |

这一层直接消灭今天的两个大头：42 分钟卡死 + 50KB 原始输出进上下文。

### L3 检材索引（32G 的唯一办法）

```bash
fcase index chan        # 纯脚本，无模型
```

`meta/index/chan.json`（2–5KB）：

```json
{"artifact":"CHAN","kind":"ios-backup","files":1880,"bytes":249278021,
 "databases":[{"path":"var/mobile/Media/PhotoData/Photos.sqlite",
               "tables":{"ZASSET":1203,"ZPERSON":45}}],
 "apps":[{"bundle":"com.tencent.xin","files":320}],
 "time_range":["2019-01-01","2025-05-16"],
 "key_files":{"keychain":"var/keychains/keychain-backup.plist","manifest":"var/Manifest.db"}}
```

之后每题只读索引，不再 `find` 全盘。今天 94 条命令里约 60 条在重复这件事。

### L4 Subagent：按检材分，不按题分

用 example 的 `subagent` 工具，agent 定义放 `~/.pi/agent/agents/`：

```markdown
---
name: collector
description: 在一个检材内取数，只返回结构化 JSON
tools: bash, read
---
```

调用：

```
subagent({ agent: "collector", task: "CHAN 备份里找微信号/邮箱/交易记录，按 schema 输出" })
```

- 独立 `pi` 进程、独立上下文
- 输出**只允许 JSON**，落到 `meta/sub/Q07-chan.json`：

```json
{"artifact":"CHAN","findings":[{"text":"...","locator":"...","confidence":0.9}],
 "deadends":["Realm 需 npm 原生模块，放弃"],"tokens_used":12345}
```

- 主 agent 只读这几百字节，**永不读子 agent 原始输出**
- 可并发 2–3，但**同一检材不并发**（9p 上争抢）

### L5 固化：三层保险

1. guard 自动写 `cmdlog.jsonl` —— 模型什么都不记也能回溯
2. 每 10 条命令提示一次
3. `solve` 退出校验：本会话 0 条 note → 不标 done，写 `doing` 并把 cmdlog 摘要塞进下一版 brief

## 5. 数据格式

```json
// questions.json
{"case":"test","questions":[
  {"id":"Q07","group":"陈民浩手机","artifact":"CHAN","type":"single",
   "choices":["A","B","C","D"],"stem":"...","points":1,
   "skills":["mobile"],"status":"todo","answer":null,"cost":1}
]}
```

`evidence.db` 表：

| 表 | 字段 |
|---|---|
| findings | id, qid, kind, text, locator, src, confidence, created_at |
| answers | qid UNIQUE, answer, evidence, confidence, created_at |
| deadends | id, qid, text, created_at |
| pending_installs | id, pkg, reason, qid, created_at |

## 6. 安装请示流程

```
agent:  fcase need npm:realm --reason "解析 sa.realm 需要 node 绑定"
        → 写 pending-install.md，打印「已记录，请结束本轮等人工处理」
        → guard 同时拒绝后续任何安装命令
人:     看清单 → 决定装/不装 → 手动装 → fcase install-done npm:realm
agent:  solve Q07 --resume
```

## 7. 验收标准

- 98 题里 ≥20 题在 2 小时内完成
- 单题会话：平均 < 8 分钟、< 40k tokens、**0 次压缩**
- **0 次**未经请示的安装
- 每题答案都有 locator，且 `board` 能一眼看出进度

## 8. 实施顺序（4 步，每步可独立验证）

| 步 | 内容 | 验证 |
|---|---|---|
| 1 | `fcase import/board/next/show/brief` + `questions.json` | 纯 python，立刻看到 98 题看板 |
| 2 | `guard.ts` + `solve`（单题闭环，先不接 subagent） | 跑 Q01，看截断/超时/拒绝安装是否生效 |
| 3 | `fcase index` + 接 example 的 `subagent` | 起 2 个 collector 并行扫 CHAN/FUNG |
| 4 | `bin/eval`（3 个已知答案的小 case） | 改动前后跑一遍，确认没有退步 |

代码量估计：`fcase` +300 行、`guard.ts` ~180 行、`solve` ~120 行、`index` ~150 行。
