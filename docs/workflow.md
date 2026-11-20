# 一道题的完整流程

## 0. 准备（每台机器一次）

```bash
cd ~/projects/forensics
./setup.sh --check
```

## 1. 建 case

```bash
./bin/case ap3
```

得到：

```
$CASES_ROOT/ap3/
├── evi/      ← 放检材
├── work/     ← 中间产物
└── meta/
    ├── question.md
    └── notes.md
```

把题目写进 `meta/question.md`，检材用 `add` 软链进来：

```bash
cd $CASES_ROOT/ap3
~/projects/forensics/bin/add /path/to/evidence/*
```

`evi/` 是 555 锁着的，`add` 会临时解锁、软链、再锁上。
30GB 的镜像不用复制，也不占第二份空间。

> 不要 `add /mnt/d` 这种整个盘 —— `fcase ls` 会遍历所有东西。

## 2. 先自己看一眼（30 秒，很值）

```bash
cd $CASES_ROOT/ap3
fcase ls
file evi/*
```

知道有什么类型，才好判断模型有没有在瞎说。

## 2.5 解包

```bash
unpack -l evi/mobile.zip            # 先看内容
unpack evi/mobile.zip               # 解到 work/unpack/mobile/
unpack -p 'PASSWORD' evi/locked.zip # 加密包
```

`unpack` 只往 `work/` 写，并检查 `../` 穿越、解压后总大小（默认 20G）、
文件数（默认 20 万）、嵌套深度（默认 3 层）。

## 3. 起 agent

```bash
~/projects/forensics/bin/ask
```

或者直接给问题：

```bash
~/projects/forensics/bin/ask "USB 镜像里有几个分区？起始偏移多少？"
```

继续上次会话：

```bash
~/projects/forensics/bin/ask -c
```

## 4. 模型干活时你在看什么

它会：

1. `fcase ls` → `file evi/*` 摸底
2. 加载对应技能（`disk` / `pcap` / ...）
3. 跑命令，输出全在 `work/`
4. `fcase note ... --locator ...` 边查边记
5. `fcase answer ... --evidence ...` 给结论

**你要盯的是第 4 步**：locator 是不是具体值，不是"看 mmls 输出"这种废话。

## 5. 收尾

```bash
fcase status
cat meta/answers.md
```

`meta/answers.md` 就是可以直接提交的东西。

## 6. 复盘（可选，但推荐）

```bash
cat meta/findings.md      # 线索链
cat meta/notes.md         # 你手写的
ls work/                  # 中间产物，确认没往 evi 里写东西
```

确认 `evi/` 没被改：

```bash
ls -la --time-style=full-iso evi/
```

## 常见情况

| 情况 | 怎么做 |
|---|---|
| 模型说"找不到" | 自己跑一遍技能里的命令，确认工具装没装（`./setup.sh --check`） |
| 模型给了错的 locator | 直接 `fcase note` 记一条更正，别改历史 |
| 一道题有多问 | 每问一个 `fcase answer`，不要合并 |
| 检材太大跑不动 | 先 `cp` 到 `~/scratch/`，或 `editcap` 切片 |
| 想换模型 | `ask --model xxx`，或改 `~/.pi/agent/settings.json` |

## 批量做题

```bash
for c in case1 case2 case3; do
  cd $CASES_ROOT/$c
  ~/projects/forensics/bin/ask "做完 meta/question.md 里的所有题" 
done
```

每道题独立 case，答案各自在 `meta/answers.md`。
