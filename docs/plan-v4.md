# 设计 v4：主 agent 调度 + 分组并行 + 可读的中间产物

> 状态：**待确认**。确认后按 §7 的顺序改代码。
> 取代 `design-v3.md`（v3 只解决了"逐题驱动"，没解决分类、并行调度、产物可读性）。

## 0. 你提的六个问题 → 六个决策

| # | 问题 | 决策 |
|---|---|---|
| 1 | 查看方式太杂 | **所有命令收进 `fcase` 一个入口，只有 5 个动词**（§2） |
| 2 | 线索太杂 | **一切中间产物按「检材/题组」落盘 + 每层一份 INDEX.md**（§3） |
| 3 | 分类与关联 | **新增 intake 阶段**：建 `map.json` 描述 检材↔人物↔题组↔依赖（§4） |
| 4 | 并行 | **按题组切分 worker，默认 4 并发**，每组独立目录互不冲突（§5） |
| 5 | 换模型 | **attempts 追加表**，一次没做出来再换模型，历史全部保留（§6） |
| 6 | 主 agent | **main 常驻调度**，worker 干活，sub 做单点深挖；卡住主动喊人（§5.3） |

底层还有个没说但必须解决的：**慢**。§8 给了实测数据和三条硬措施。

---

## 1. 三层 agent

```
main（常驻，1 个）
  │  读 map.json 派活 / 看心跳 / 汇总答案 / 卡住喊人 / 回答你的提问
  ├── worker A   FUNG 手机 · WhatsApp 组（Q47–Q61）
  ├── worker B   LEUNG U盘 · 容器组（Q91–Q98）
  ├── worker C   CHAN 手机 · Photos 组（Q23–Q44）
  └── worker D   …
        └── sub  单点深挖（"把这个 7z 解开"/"查这条交易的对手方"）
```

| 角色 | 数量 | 职责 | 不做什么 |
|---|---|---|---|
| main | 1 | 分类、派活、汇总、催办、回答你 | 不亲自查证据 |
| worker | ≤4（可调） | 一个题组从头做到尾 | 不跨组、不改别人的目录 |
| sub | 临时 | 一个明确的小任务，返回 JSON | 不做判断，只取数 |

**main 的四个硬职责**（这是 v3 缺的）：
1. 拿到题目先分类（§4），分类结果先给你确认再开工
2. 卡住超过 N 分钟 → 写 `meta/blocked.md` 并在终端高亮（装软件、缺密码、方向错）
3. 汇总：每题产出 `writeups/Qxx.md`
4. 你问"现在怎么样"时，它答得出来（读 board，不现查）

---

## 2. 命令：只剩 5 个

现在 `bin/` 有 12 个脚本（live / watch-case / trace / solve / solve-par / ask / case / add / unpack / fcase / eval / …）。
收敛成一个入口，**其它全部变成 `fcase` 的动词或内部实现**。

| 命令 | 干什么 | 对应你原来的诉求 |
|---|---|---|
| `fcase board` | 进度 + 每个 agent 在做什么 + 卡在哪 | "看当前做题进度" |
| `fcase attach [A1]` | **实时进到某个 agent 里看它在想什么**（只读流） | "进到目前跑的 agent 里" |
| `fcase answers` | 答案表（题号/答案/置信度/证据） | "看答案" |
| `fcase why Q07` | 这道题的题解：怎么查到的、走过哪些死路、换过几个模型 | "查看题解" |
| `fcase agents` | 所有 agent 一览：状态/题组/已跑时长/当前动作 | "看有哪些 agent" |

**保留但隐藏**（不给用户记）：`fcase go`（main 自己跑的入口）、`fcase import`、`fcase map`。
旧的 `solve`/`solve-par`/`live`/`trace`/`watch-case` 收进 `bin/internal/`，由 `fcase` 调用，不再出现在你的肌肉记忆里。

`fcase` 不带参数时打印**一屏说明书**（5 个命令 + 当前 case 一句话状态），不列 20 个子命令。

---

## 3. 目录：中间产物按检材/题组分家

```
<case>/
  evi/                          原始检材（555，只读）
  meta/
    questions.md                题目原文（人读）
    map.md / map.json           分类与依赖（§4）
    board.md                    进度（自动生成）
    answers.md                  答案表（自动生成）
    writeups/Q07.md             每题题解（自动生成 + 人工可补）
    blocked.md                  卡住待人工处理
    evidence.db                 findings / answers / attempts / agents
  artifacts/                    ★ 所有中间产物，按检材分文件夹
    FUNG_CC_mobile/
      INDEX.md                  ★ 这个检材：包含什么、产出过哪些文件、对应哪些题
      whatsapp/                 解包出来的 WhatsApp 数据库
      photos/
      Q47-Q61/                  这一组题的产物（导出物、截图、查询结果）
        wechat_id.txt
        notes.md
    AP3_LEUNG_YL_USB/
      INDEX.md
      exfat/                    fls 清单、导出的文件
      fat16/
      Q91-Q98-xcontainer/       容器解出来的东西
        files/
  scratch/                      临时文件，随时可删，不进 git
```

**三条规则**：

1. **一个检材一个顶层文件夹**，名字 = 检材 stem。人一眼能对上。
2. **组内产物进 `Qxx-Qyy/`**，不散落在 `work/`。同一组的连续题共享一个目录，方便"承上题"。
3. **每层一份 `INDEX.md`**（自动生成，可人工补）：
   - 这个目录是什么
   - 有哪些文件、每个文件是什么（一句话）
   - 对应哪些题

`INDEX.md` 就是你说的"通过一个 md 文档来关联题目和中间文件的位置"。它同时是
worker 的入口（先读 INDEX，不用满盘 find）和你手动做题的索引。

---

## 4. intake：给模板，让主 agent 自己分类

**不做关键词硬编码** —— 每套题的领域都不一样，写死的规则换个 case 就废。

分三步，人和 agent 各管一段：

```
fcase plan              → 生成 meta/plan-in.md（题目+检材清单）
                          + meta/map.json（空模板）
       ↓
主 agent 读 prompts/plan.md 的规则，读 plan-in.md，
写出 meta/map.json（题组/依赖/预估工时）
       ↓
fcase plan --apply      → 校验（漏题/重题/检材不存在/依赖指向错误）+ 入库
                          + 渲染 meta/map.md + artifacts/*/INDEX.md + 建组目录
```

**模板规定的是"形状"，不是"内容"**：

| 字段 | 说明 |
|---|---|
| `id` / `name` | 组号 + 人话名字（6–12 字） |
| `artifact` | 绑定的检材（必须存在于 evi/） |
| `qids` | 题号数组，**必须覆盖全部题目且不重复**（apply 会校验） |
| `depends` | 依赖哪些组的产物（如"钱包题依赖解容器组"） |
| `est_min` | 预估工时，用于调度排序 |

`prompts/plan.md` 里给了分类原则（同组 = 同一份中间产物 + 连续问题链；
组大小 3–10 题；换检材必换组；依赖要标出来；先易后难），但**具体怎么分由 agent 判断**。

`fcase plan --auto` 只是兜底（按检材 + 连续 8 题硬切），用于没有 agent 时先跑起来，
它自己会在 `reason` 里注明"建议让 agent 重新分类"。

### map.md 长什么样（人工可读）

```markdown
## FUNG_CC_mobile  FUNG_CC_mobile.zip  1.1G  ios-dump
- **G17** WhatsApp 账号与社群  `Q49–Q58`（10 题，约 85 分钟）
  - 这 10 题都在查同一份 ChatStorage.sqlite，Q50 起为承上题
- **G15** Poe 对话  `Q43–Q46`（4 题，约 40 分钟）　依赖 无
```

## 5. 并行调度

### 5.1 切分单位 = 题组（不是题，也不是检材）

- 同组题共享中间产物 → 必须同 worker、顺序做（`--batch` 已有，沿用）
- 不同组互不依赖 → 可并行
- 一个检材下可以有多组同时跑（只要产物目录不同）

### 5.2 并发数与资源

| 资源 | 限制 |
|---|---|
| 并发 worker | 默认 4，`--jobs` 可调 |
| 每组超时 | 默认 30 分钟/题，组内累计上限 3 小时 |
| CPU | 明确禁止 worker 起多核爆破（guard 已有规则） |
| 磁盘 | 每组产物在自己目录，不写别人的 |

### 5.3 主 agent 的调度循环

```
while 有未完成的组:
    挑一个空闲 worker
    从 map.json 取下一个组（先易后难 / 优先解锁下游的组）
    起 worker，写 agents 表（组、模型、开始时间、session 路径）
    心跳：每 60s 更新一次"当前题号 + 最后一条命令"
    若 worker 超过 40 分钟无进展 → 标记 stalled，写 blocked.md，通知你
    若 worker 退出 → 检查该组每题是否都有 answer，缺的记 attempts 失败
```

**卡住喊你**的三种情形（对应你说的"安装什么软件"）：
- 需要装包 → `blocked.md` 写清包名/原因，终端高亮
- 缺密码/密钥 → 写清缺什么、试过哪些候选
- 连续两次超时 → 建议换模型或人工介入

---

## 6. 换模型与修改记录

新增 `attempts` 表（**只追加，不覆盖**）：

```
qid | attempt | model | started | ended | status | session_path | note
Q92 | 1       | glm-5.3  | ...  | ...   | timeout | sessions/...jsonl | 容器打不开
Q92 | 2       | kimi-k2.7| ...  | ...   | solved  | sessions/...jsonl | 换模型后成功
```

规则：
- 每次 `fcase run Q92 --model X` 追加一行，**旧的答案和线索不删**
- `fcase why Q92` 会把所有 attempt 按时间排开，标出最终采纳的是哪次
- 旧线索不删除，但打 `superseded_by` 标记；简报默认只喂**最新 attempt 的线索**，
  避免上次的错误结论污染这次（这次 Q11/Q18/Q23 复现旧答案就是这么来的）

---

## 7. 实施顺序（每步可单独验收）

| 步 | 内容 | 验收标准 |
|---|---|---|
| **1** | `fcase` 命令收敛 + 目录改造（artifacts/ + INDEX.md） | ✅ 5 条命令能跑 |
| **2** | intake：模板 + agent 分类 + `--apply` 校验 | ✅ 漏题/重题/依赖错误都能拦住 |
| **3** | 主调度器 + agents 表 + blocked.md | ✅ 按组派活、依赖解锁、失败记 blocked 并继续 |
| **4** | attempts 隔离 + `fcase why` 按轮次展示 | ✅ 简报只喂当前 attempt，旧线索归档可查 |
| **5** | 提速三件事（§8） | ✅ stage / deep-index / 组内 batch 都已落地 |

前两步是地基，必须先做；3/4 可并行开发。

---

## 8. 提速：实测数据与三条硬措施

上一场 98 题的实际耗时分布（Q81 会话实测）：

| 项 | 数值 |
|---|---|
| 命令执行 | 1441s（57%） |
| 模型/网络等待 | 1107s（43%） |
| 最慢单条命令 | `fls -r` 在 9p 上 300s（被杀） |

**措施 1：检材 stage 到原生盘（最大收益）**

```
同一份 E01：/mnt/d 上 fls -r 180s 跑不完；~/scratch 上 16s 跑完
```

`fcase stage` 把检材复制/解包到 `~/scratch/<case>/`，所有工具只读那里。
`evi/` 保留为原始证据（只读、算 hash），工具不直接读它。

**措施 2：索引一次，复用到底**

现在每题都重跑 `fls -r`。改成 intake 阶段一次性生成完整清单
（`artifacts/<检材>/exfat/fls.txt`），worker 只 `rg` 清单，不重跑扫描。

**措施 3：组内 batch + 组间并行**

同组题一个会话连做（`--batch` 已有），组间 4 并发。理论上 98 题从
"串行 12 分钟/题" 降到 "并行 4 组 × 组内 batch"。

---

## 9. 已完成（第 1–3 步）

- `fcase` 五个动词：board / attach / answers / why / agents
- `fcase plan` → 模板 → agent 填 `map.json` → `--apply` 校验入库
- `fcase go` → `bin/internal/scheduler.py`：按组派活、依赖解锁、每题一个 attempt、
  失败写 `meta/blocked.md` 后继续、组产物落 `artifacts/<检材>/<组>/logs/`
- 表：`groups` / `agents` / `attempts`
- **attempt 隔离**：`findings.attempt` 列；简报只喂当前 attempt 的线索，旧线索归档并在
  简报里提示"此前有 N 条旧线索已归档"；`fcase why` 按轮次展示
- **提速**：`fcase stage`（原生盘副本，默认跳过 >4G）、`fcase deep-index`（fls 清单一次生成、
  全组复用）、`fcase go --batch N`（组内多题共享一个会话）

五步全部完成。

## 10. 需要你定的三件事

1. **并发数**：默认 4，还是按核数自动（24 核 → 6）？
2. **map 确认**：intake 后是先给你看 `map.md` 再开工，还是直接开工、你想看再看？
3. **老 case 怎么办**：上一套 98 题要迁移到新目录结构，还是新 case 才用新结构？
