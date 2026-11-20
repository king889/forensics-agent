# 配置模型

**凭据永远不进仓库。** 仓库里只有 `config.json`，写的是"用哪个 provider、哪个模型"：

```json
{
  "provider": "<provider 名>",
  "model": "<模型 ID>",
  "thinking": "off"
}
```

key 一律由 Pi 自己从 `~/.pi/agent/`（或环境变量）解析。
所以换机器后**唯一要手动做的一步就是给 Pi 配一个能用的模型**。

先自检：

```bash
fcase doctor            # 工具 + pi + 凭据 + 实际调用，一次查完
fcase doctor --no-net   # 只查配置，不花 token
```

---

## 先分清两种情况

| 情况 | 要不要写 `~/.pi/agent/models.json` |
|---|---|
| 用 Pi **内置** provider（openai / anthropic / deepseek / gemini / openrouter / groq / xai / moonshot / qwen / minimax / zai / github-copilot …） | **不用**，直接配 key |
| 用**自建或第三方聚合网关**（OpenAI 兼容 `/v1`） | 要，加一段 provider 定义 |
| 用**本地模型**（ollama / vLLM / llama.cpp） | 要，baseUrl 指向 `127.0.0.1` |

内置 provider 的完整列表和各自的环境变量名见 Pi 文档 `docs/providers.md`。

---

## 情况一：内置 provider

### 方式 A：环境变量（key 不落盘）

```bash
# 举例，换成你在用的那家
export OPENAI_API_KEY=sk-...            # openai
export ANTHROPIC_API_KEY=sk-ant-...     # anthropic
export DEEPSEEK_API_KEY=sk-...          # deepseek
export OPENROUTER_API_KEY=sk-or-...     # openrouter
export GEMINI_API_KEY=...               # gemini
```

写进 `~/.bashrc` / `~/.zshrc` 长期生效。然后改 `config.json`：

```json
{ "provider": "deepseek", "model": "deepseek-chat" }
```

### 方式 B：让 Pi 存起来

```bash
pi auth login deepseek --api-key        # 提示时粘贴 key
pi auth check --provider deepseek       # → ready
```

key 进 `~/.pi/agent/auth.json`（权限 600，Pi 自己管）。

### 常见内置 provider 与模型 ID

| provider | 环境变量 | 模型 ID 举例 |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-5`, `gpt-4.1`, `o4-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5`, `claude-opus-4-1` |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat`, `deepseek-reasoner` |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-pro`, `gemini-2.5-flash` |
| `openrouter` | `OPENROUTER_API_KEY` | `anthropic/claude-sonnet-4.5`、`qwen/qwen3-235b` 等 |
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `moonshot` | `MOONSHOT_API_KEY` | `kimi-k2` |
| `qwen` | `QWEN_TOKEN_PLAN_API_KEY` | `qwen3-max` |

模型 ID 以各家文档为准；`pi` 交互模式下 `/model` 可以列出当前 provider 下的可用模型。

---

## 情况二：自建 / 第三方 OpenAI 兼容网关

```bash
mkdir -p ~/.pi/agent
cp templates/models.json ~/.pi/agent/models.json
```

编辑里面 `mygateway` 那段：

```json
{
  "providers": {
    "mygateway": {
      "name": "My Gateway",
      "baseUrl": "https://your-endpoint.example.com/v1",
      "api": "openai-completions",
      "apiKey": "$MYGATEWAY_API_KEY",
      "models": [
        { "id": "vendor/model-name",
          "name": "Model Name",
          "reasoning": false,
          "input": ["text", "image"],
          "contextWindow": 128000,
          "maxTokens": 16384 }
      ]
    }
  }
}
```

然后：

```bash
export MYGATEWAY_API_KEY="你的key"
```

`config.json` 里：

```json
{ "provider": "mygateway", "model": "vendor/model-name" }
```

**注意三点**，这是最容易错的地方：

1. `config.json.provider` 必须等于 `models.json.providers` 里的**键名**（不是 `name` 字段）
2. `config.json.model` 必须等于该 provider 下 `models[].id`
3. `apiKey` 写 `$ENV_NAME` 时，环境变量名要和这里一致

`baseUrl` 一般以 `/v1` 结尾；`api` 用 `openai-completions` 覆盖绝大多数网关。

---

## 情况三：本地模型

ollama：

```bash
ollama serve
ollama pull qwen3:32b
```

`models.json` 用模板里的 `local` 段（baseUrl `http://127.0.0.1:11434/v1`，apiKey 随便填），
`config.json` 写 `{"provider": "local", "model": "qwen3:32b"}`。

vLLM：

```bash
vllm serve <模型路径> --port 8000
```

用模板里的 `vllm` 段。

本地模型的注意点：

- 上下文窗口要够大（取证单题常见 30k–200k token），不够会被截断导致结论缺失
- 工具调用能力要过关，否则 agent 不会正确调用 `fls` / `rg`
- 速度慢时把 `config.json` 的 `jobs` 调小，避免并发把显存打满

---

## 换 provider / 换模型

改 `config.json` 即可，不用改代码。命令行参数优先：

```bash
fcase run --provider openrouter --model anthropic/claude-sonnet-4.5
fcase go --provider deepseek --model deepseek-reasoner --thinking low
```

也可以用环境变量临时切换（`bin/solve` 会透传给 pi）：

```bash
FCASE_PROVIDER=openai FCASE_MODEL=gpt-5 fcase run
```

## 选模型的几个标准

取证流水线的负载特点：**大量短命令 + 长清单检索 + 偶尔需要严格推理**。

| 维度 | 建议 |
|---|---|
| 速度 | 单题平均 20–40 次工具调用，输出速度直接影响墙钟 |
| 成本 | 输入 token 远大于输出（清单检索为主），按输入价挑更划算 |
| 上下文 | ≥ 128k，否则长清单会被截断 |
| 工具调用 | 必须稳定支持 function calling，弱模型会漏参数或瞎编命令 |
| 思考档位 | `thinking: "off"` 对机械提取够用；需要推理的题再对单组开 `low`/`medium` |

一个便宜的快模型 + `fcase probe` 预计算候选表，通常比换贵模型更有效。

## 检查清单

- [ ] `fcase doctor` 全绿
- [ ] `pi --provider <p> --model <m> -p "只回复 OK"` 能返回
- [ ] `config.json.provider` 与 `models.json` 键名 / 环境变量名三者一致
- [ ] `~/.pi/agent/models.json` 与 `auth.json` 不在任何 git 仓库里
- [ ] 分享项目前确认 `git log -S "sk-"` 为空
