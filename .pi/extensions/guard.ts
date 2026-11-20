/**
 * guard.ts —— 取证会话的 bash 守卫（替换内置 bash 工具）
 *
 * 为什么要有这一层：`$CASES_ROOT/test` 那场 68 分钟的会话里，
 *   - 42 分钟卡在 `npm install realm`（没有超时）
 *   - 单条命令 50KB 原始输出直接进上下文，3 次压缩全部白干
 *   - 168 条命令 0 次 fcase note（全靠模型自觉，失败）
 * 这些都不能靠提示词，只能在工具层强制。
 *
 * 规则：
 *   1. 输出 > 8KB → 全文落 work/out/，模型只看到头 40 行 + 尾 15 行 + 路径
 *   2. 默认 180s 超时，超时 kill 进程组
 *   3. 安装命令（npm/pip/uv/apt/dpkg/install.sh）→ 拒绝执行，写 meta/pending-install.md
 *   4. sudo → 拒绝（WSL 会卡在密码提示上）
 *   5. 写 evi/ → 拒绝
 *   6. 每条命令 append meta/cmdlog.jsonl；每 10 条提示一次「该记录了」
 *   7. 输出超过 64MB → 直接 kill，让模型去过滤
 */

import { spawn } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const MAX_OUTPUT_BYTES = 3 * 1024;   // 实测：8KB × 38 条命令 = 76k token 上下文，是最大隐性成本
const HARD_OUTPUT_LIMIT = 64 * 1024 * 1024;
const DEFAULT_TIMEOUT_S = 180;

// 按工具设超时：fls 在几十万条目上要 200s+，一刀切 180s 会白跑
function loadConfig(): Record<string, any> {
	try {
		const root = resolve(process.env.FORENSICS_ROOT || join(__dirname, "..", ".."));
		return JSON.parse(readFileSync(join(root, "config.json"), "utf8"));
	} catch {
		return {};
	}
}
const CFG = loadConfig();
const TOOL_TIMEOUTS: Record<string, number> = CFG.tool_timeouts || {};
const ATTEMPT_MAX_CALLS = Number(CFG.attempt_max_calls || 0);

function timeoutFor(cmd: string): number {
	for (const [tool, secs] of Object.entries(TOOL_TIMEOUTS)) {
		// 只认命令词（前 200 字符内出现独立单词），避免误配
		if (new RegExp(`(^|[\\s|;&(/'\"])${tool.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([\\s|;&)'\"]|$)`).test(cmd.slice(0, 400))) {
			return Number(secs) || DEFAULT_TIMEOUT_S;
		}
	}
	return DEFAULT_TIMEOUT_S;
}

// 病态命令：不是「危险」，是「注定跑不完还占满超时」，直接给替代方案
const PATHOLOGIC: Array<[RegExp, string]> = [
	[/\bfind\s+\/\s/, "不要全盘 find。用 `work/<检材>/listing.txt`（已生成）配合 rg。"],
	[/\bgrep\b[^|]*\s-[a-zA-Z]*a[a-zA-Z]*\b[^|]*\bevi\//, "不要在原始镜像上直接 grep。先 `fcase deep-index <检材>` 出清单，再用 rg 查清单。"],
	[/\b(sleep)\s+([2-9]\d|\d{3,})\b/, "不要长 sleep 等后台任务。先做别的题，下一轮再回来查。"],
	[/\bfor\s+\w+\s+in\b[^;|]{0,160}\bicat\b[^;|]{0,80}\bdo\b/, "不要逐 inode 循环 icat（每个都重开镜像）。用 `fcase extract <检材> --grep '<路径正则>'`。"],
];
const HEAD_LINES = 40;
const TAIL_LINES = 15;
const NUDGE_EVERY = 10;

const params = Type.Object({
	command: Type.String({ description: "Shell command to execute" }),
	timeout: Type.Optional(Type.Number({ description: "超时秒数（默认 180）" })),
});

/** 需要人工批准的安装动作 —— 一律拒绝，让 agent 停下来请示。 */
const INSTALL_PATTERNS: Array<[RegExp, string]> = [
	[/\b(npm|pnpm|yarn|bun)\s+(i|install|add|ci|create)\b/, "node 包"],
	[/\bpip3?\s+install\b/, "python 包"],
	[/\buv\s+(pip\s+install|tool\s+install|add)\b/, "python 包（uv）"],
	[/\b(apt|apt-get)\s+(-\S+\s+)*install\b/, "apt 包"],
	[/\bdpkg\s+(-i|--install)\b/, "deb 包"],
	[/\b(conda|mamba)\s+install\b/, "conda 包"],
	[/\bgem\s+install\b/, "ruby gem"],
	[/\bcargo\s+install\b/, "rust crate"],
	[/\bgo\s+install\b/, "go 模块"],
	[/\bbrew\s+install\b/, "brew 包"],
	[/tools\/install\.sh/, "本仓库安装脚本"],
];

/** 往 evi/ 写的动作（evi 是 555，但软链和 root 仍可能绕过）。
 *  只认「重定向目标」和「明确写操作」，别把字符串里提到的 evi/ 也算上
 *  —— guard 自己就写过 `cp evi/x work/x` 这种提示，不能自我拦截。 */
const EVI_WRITE_PATTERNS: RegExp[] = [
	/(?:^|[^<>])>{1,2}\s*["']?evi\//,
	/\b(?:rm|mv|ln|tee|touch|truncate|install|chmod|chown)\b[^|;&\n]*\s["']?evi\//,
	/\bdd\b[^|;&\n]*\bof=["']?evi\//,
];

function findCaseRoot(cwd: string): string | undefined {
	const env = process.env.FCASE_ROOT;
	if (env && existsSync(join(env, "meta"))) return env;
	let dir = resolve(cwd);
	for (let i = 0; i < 12; i++) {
		if (existsSync(join(dir, "meta"))) return dir;
		const parent = resolve(dir, "..");
		if (parent === dir) break;
		dir = parent;
	}
	return undefined;
}

function blocked(text: string, patterns: RegExp[]): RegExp | undefined {
	return patterns.find((re) => re.test(text));
}

/**
 * 按内容形态裁切，尽量保留"有用的行"而不是无脑头+尾。
 *
 * 背景：实测 8KB 上限 × 38 条命令 = 76k token 上下文，是最大隐性成本；
 * 但直接压到 3KB 会让 agent 看不到关键命中行、被迫重跑，反而更慢。按形态分流：
 *   - 行式清单（fls/rg/ls 结果，行短且多）→ 逐行装满预算
 *   - 散落的关键行（error/password/inode/Q编号等）→ 补进来
 *   - 大段文本 → 头 + 尾
 */
function smartClip(text: string, maxBytes: number): { body: string; kept: number; total: number } {
	const lines = text.split("\n");
	const total = lines.length;
	const sample = lines.slice(0, Math.min(200, total));
	const avgLen = sample.reduce((a, l) => a + l.length, 0) / Math.max(1, sample.length);

	if (avgLen < 200) {
		const keep: string[] = [];
		let used = 0;
		for (const line of lines) {
			if (used + line.length + 1 > maxBytes) break;
			keep.push(line);
			used += line.length + 1;
		}
		if (keep.length < total) {
			const KEY = /(error|fail|denied|not found|password|secret|token|flag|inode|\bQ\d{2}\b)/i;
			const picked = lines.filter((l) => KEY.test(l)).slice(0, 20);
			if (picked.length) keep.push("… （关键行）…", ...picked);
		}
		return { body: keep.join("\n"), kept: keep.length, total };
	}
	return { body: headTail(text, maxBytes), kept: HEAD_LINES + TAIL_LINES, total };
}

function headTail(text: string, maxBytes: number): string {
	const lines = text.split("\n");
	// 头和尾各占一半预算，确保总体不超 maxBytes（之前 tail 无上限，会超 3 倍）
	const half = Math.floor(maxBytes / 2);
	const headRaw = lines.slice(0, HEAD_LINES).join("\n");
	const tailRaw = lines.slice(-TAIL_LINES).join("\n");
	const headCut = headRaw.length > half ? headRaw.slice(0, half) + "\n…（头部截断）" : headRaw;
	const tailCut = tailRaw.length > half ? "…（尾部截断）\n" + tailRaw.slice(tailRaw.length - half) : tailRaw;
	const omitted = Math.max(0, lines.length - HEAD_LINES - TAIL_LINES);
	return `${headCut}\n\n…（中间省略 ${omitted} 行 / ${(text.length / 1024).toFixed(0)}KB）…\n\n${tailCut}`;
}

function minutesSince(tsMs: number): string {
	const m = Math.floor((Date.now() - tsMs) / 60000);
	return m < 1 ? "刚刚" : `${m} 分钟前`;
}

export default function guardExtension(pi: ExtensionAPI) {
	let count = 0;

	pi.registerTool({
		name: "bash",
		label: "bash",
		description:
			"执行 shell 命令。守卫：输出超过 8KB 自动落盘只回摘要、默认 180 秒超时、安装命令与 sudo 被拒绝、禁止写 evi/。",
		parameters: params,

		async execute(_toolCallId, p, signal, _onUpdate, ctx) {
			const cwd = ctx.cwd;
			const cmd = p.command;
			const caseRoot = findCaseRoot(cwd);
			const timeoutS = p.timeout && p.timeout > 0 ? p.timeout : timeoutFor(cmd);
			count++;

			const logLine = (extra: Record<string, unknown>) => {
				if (!caseRoot) return;
				// 调度器起 worker 时会带上 FCASE_AGENT / FCASE_QID，用于按 agent 统计进度
				const who: Record<string, unknown> = {};
				if (process.env.FCASE_AGENT) who.agent = process.env.FCASE_AGENT;
				if (process.env.FCASE_QID) who.qid = process.env.FCASE_QID;
				try {
					appendFileSync(
						join(caseRoot, "meta", "cmdlog.jsonl"),
						JSON.stringify({ ts: new Date().toISOString(), cwd, cmd, ...who, ...extra }) + "\n",
					);
				} catch {
					/* 日志失败不影响命令 */
				}
			};

			// ⓪ 病态命令拦截：省下必然超时的几分钟
			const bad = PATHOLOGIC.find(([re]) => re.test(cmd));
			if (bad) {
				logLine({ exit: "rejected", ms: 0, bytes: 0, rejected: "pathologic" });
				return {
					content: [{ type: "text", text: `[guard] 已拒绝：${bad[1]}` }],
					isError: true,
				};
			}

			// ① 安装拦截
			const install = INSTALL_PATTERNS.find(([re]) => re.test(cmd));
			if (install) {
				const pkg = install[1];
				if (caseRoot) {
					try {
						appendFileSync(
							join(caseRoot, "meta", "pending-install.md"),
							`\n## ${new Date().toISOString()}\n\n- 命令：\`${cmd}\`\n- 类型：${pkg}\n- 目录：\`${cwd}\`\n`,
						);
					} catch {
						/* ignore */
					}
				}
				logLine({ exit: null, blocked: "install" });
				return {
					content: [
						{
							type: "text",
							text: [
								`[guard] 已拦截安装命令（${pkg}）：${cmd}`,
								"",
								"规则：agent 不自己装东西。已记入 meta/pending-install.md。",
								"现在立刻停下，不要重试、不要换命令绕过。用一段话告诉用户：",
								"  1) 要装什么 2) 为什么这道题需要它 3) 有没有不装的办法（通常是 strings/python 库）。",
								"等用户装完再继续。",
							].join("\n"),
						},
					],
					isError: true,
				};
			}

			// ② sudo
			if (/(^|[|;&]\s*)sudo\b/.test(cmd)) {
				logLine({ exit: null, blocked: "sudo" });
				return {
					content: [
						{
							type: "text",
							text: "[guard] sudo 被拒绝：WSL 的 sudo 会卡在密码提示上，把会话拖死。\n需要 root 的操作请写进 pending-install.md 让用户处理。",
						},
					],
					isError: true,
				};
			}

			// ③ 写 evi/
			if (blocked(cmd, EVI_WRITE_PATTERNS)) {
				logLine({ exit: null, blocked: "evi-write" });
				return {
					content: [
						{
							type: "text",
							text: "[guard] 拒绝写入 evi/。中间产物写 work/，需要副本就 `cp evi/x work/x`。",
						},
					],
					isError: true,
				};
			}

			// ④ 执行
			const started = Date.now();
			const outDir = caseRoot ? join(caseRoot, "work", "out") : undefined;
			const result = await new Promise<{ text: string; code: number | null; killed: string | null }>((done) => {
				const child = spawn("bash", ["-c", cmd], {
					cwd,
					env: { ...process.env, PI_GUARD: "1" },
					detached: true,
					stdio: ["ignore", "pipe", "pipe"],
				});

				const chunks: Buffer[] = [];
				let bytes = 0;
				let killed: string | null = null;
				let hardStopped = false;

				const onData = (b: Buffer) => {
					bytes += b.length;
					if (bytes > HARD_OUTPUT_LIMIT) {
						if (!hardStopped) {
							hardStopped = true;
							killed = "output-limit";
							try {
								process.kill(-(child.pid as number), "SIGKILL");
							} catch {
								child.kill("SIGKILL");
							}
						}
						return;
					}
					chunks.push(b);
				};
				child.stdout?.on("data", onData);
				child.stderr?.on("data", onData);

				const timer = setTimeout(() => {
					killed = "timeout";
					try {
						process.kill(-(child.pid as number), "SIGKILL");
					} catch {
						child.kill("SIGKILL");
					}
				}, timeoutS * 1000);

				const onAbort = () => {
					killed = "aborted";
					try {
						process.kill(-(child.pid as number), "SIGKILL");
					} catch {
						child.kill("SIGKILL");
					}
				};
				signal?.addEventListener("abort", onAbort);

				child.on("close", (code) => {
					clearTimeout(timer);
					signal?.removeEventListener("abort", onAbort);
					done({ text: Buffer.concat(chunks).toString("utf8"), code, killed });
				});
				child.on("error", (err) => {
					clearTimeout(timer);
					signal?.removeEventListener("abort", onAbort);
					done({ text: `无法启动 bash: ${err.message}`, code: 127, killed: "spawn" });
				});
			});

			const ms = Date.now() - started;
			let text = result.text;
			let savedPath: string | undefined;

			// ⑤ 超限输出落盘
			if (text.length > MAX_OUTPUT_BYTES && outDir) {
				try {
					mkdirSync(outDir, { recursive: true });
					const stamp = new Date().toISOString().replace(/[:.]/g, "-");
					savedPath = join(outDir, `${stamp}-${count}.txt`);
					writeFileSync(savedPath, text, "utf8");
					const rel = savedPath.slice(caseRoot!.length + 1);
					const c = smartClip(text, MAX_OUTPUT_BYTES);
					text = `${c.body}\n\n[显示 ${c.kept}/${c.total} 行；完整输出 ${(result.text.length / 1024).toFixed(0)}KB → \`${rel}\`，要别的行用 rg 过滤这个文件]`;
				} catch {
					text = smartClip(text, MAX_OUTPUT_BYTES).body;
				}
			} else if (text.length > MAX_OUTPUT_BYTES) {
				text = smartClip(text, MAX_OUTPUT_BYTES).body;
			}

			// ⑥ 状态尾巴
			const notes: string[] = [];
			if (result.killed === "timeout") {
				notes.push(`[guard] 超时 ${timeoutS}s，已 kill。换个更窄的查询，或自己加 \`timeout 30\`。`);
			} else if (result.killed === "output-limit") {
				notes.push(`[guard] 输出超过 ${HARD_OUTPUT_LIMIT / 1048576}MB，已 kill。先用 rg/head/awk 聚合，再取细节。`);
			} else if (result.killed === "aborted") {
				notes.push("[guard] 用户中断。");
			}
			if (result.code !== null && result.code !== 0 && result.killed === null) {
				notes.push(`[exit ${result.code}, ${(ms / 1000).toFixed(1)}s]`);
			}
			if (ATTEMPT_MAX_CALLS > 0 && count === ATTEMPT_MAX_CALLS) {
				notes.push(
					`[guard] 本次尝试已执行 ${count} 条命令（上限 ${ATTEMPT_MAX_CALLS}）。` +
					`现在要么提交候选答案，要么写 failure_reason 结束，不要再开新方向。`,
				);
			}
			if (count > ATTEMPT_MAX_CALLS && count % 10 === 0) {
				notes.push(`[guard] 已超出轮次预算 ${count}/${ATTEMPT_MAX_CALLS}，请收敛。`);
			}
			if (count % NUDGE_EVERY === 0 && caseRoot) {
				let last = "未知";
				try {
					last = minutesSince(statSync(join(caseRoot, "meta", "evidence.db")).mtimeMs);
				} catch {
					/* ignore */
				}
				notes.push(
					`[guard] 本会话已执行 ${count} 条命令；上次 fcase note 在 ${last}。` +
						`有结论就落盘：fcase note <kind> "..." --q Q?? --locator "..."`,
				);
			}

			logLine({
				exit: result.code,
				ms,
				bytes: result.text.length,
				saved: savedPath ? savedPath.slice(caseRoot!.length + 1) : null,
				killed: result.killed,
			});

			const body = text.trim() === "" ? "(无输出)" : text;
			const full = notes.length ? `${body}\n\n${notes.join("\n")}` : body;
			return {
				content: [{ type: "text", text: full }],
				isError: result.killed !== null || (result.code !== null && result.code !== 0),
			};
		},
	});
}
