#!/usr/bin/env node
// CyberChef 命令行 —— 直接调 CyberChef 的 Node API（不打包，用 src/node/index.mjs）
//
//   cyberchef "From Base64"                    < in > out
//   cyberchef "From Hex" "XOR" --arg key=0x42  < in
//   cyberchef "AES Decrypt" --arg key=hex:... --arg iv=hex:...
//   cyberchef -l                              列出所有操作
//   cyberchef -h "AES Decrypt"                看某个操作的参数
//   cyberchef -j "From Base64"                输出 JSON

import { readFileSync, writeFileSync } from "node:fs";

const mod = await import(
    new URL("./cyberchef/node_modules/cyberchef/src/node/index.mjs", import.meta.url)
);
const { bake, help } = mod;

const SKIP = new Set(["bake", "help", "Dish", "default"]);
const opNames = Object.keys(mod).filter((k) => typeof mod[k] === "function" && !SKIP.has(k));

function usage() {
    console.log(`用法: cyberchef [选项] <操作> [<操作> ...] [--arg 名=值 ...]

  -l, --list              列出所有操作（${opNames.length} 个）
  -h, --help-op <操作>    显示该操作的参数
  -i, --in <文件>         输入文件（默认 stdin）
  -o, --out <文件>        输出文件（默认 stdout）
  -j, --json              输出 JSON
      --arg 名=值         给前一个操作传参数，可重复
      --arg 名=hex:00ff   十六进制字节值

例子:
  echo SGVsbG8= | cyberchef "From Base64"
  cyberchef "From Hex" "XOR" --arg key=0x42 < work/blob.bin > work/out.bin
  cyberchef "Gunzip" < work/embedded.gz > work/plain
`);
}

const argv = process.argv.slice(2);
if (argv.length === 0) { usage(); process.exit(0); }

const ops = [];
let inFile = null, outFile = null, asJson = false;

for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-l" || a === "--list") {
        console.log(opNames.sort().join("\n"));
        process.exit(0);
    } else if (a === "-h" || a === "--help-op") {
        const name = argv[++i];
        const info = help(name)?.[0];
        if (!info) { console.error(`没有这个操作: ${name}`); process.exit(1); }
        console.log(`${name}  [${info.module}]\n`);
        console.log((info.description || "").replace(/<[^>]+>/g, "").trim() + "\n");
        console.log(`输入: ${info.inputType || "?"}   输出: ${info.outputType || "?"}\n参数:`);
        for (const arg of info.args || []) {
            const def = arg.value !== undefined && arg.value !== null ? JSON.stringify(arg.value) : "—";
            console.log(`  ${arg.name} (${arg.type}) 默认 ${def}`);
        }
        process.exit(0);
    } else if (a === "-i" || a === "--in") {
        inFile = argv[++i];
    } else if (a === "-o" || a === "--out") {
        outFile = argv[++i];
    } else if (a === "-j" || a === "--json") {
        asJson = true;
    } else if (a === "--arg") {
        const kv = argv[++i] || "";
        const eq = kv.indexOf("=");
        if (eq < 0 || ops.length === 0) {
            console.error(`--arg 要写成 名=值，且前面必须有操作: ${kv}`);
            process.exit(1);
        }
        const key = kv.slice(0, eq);
        let val = kv.slice(eq + 1);
        if (val.startsWith("hex:")) val = Buffer.from(val.slice(4), "hex");
        else if (val === "true" || val === "false") val = val === "true";
        else if (/^-?\d+$/.test(val)) val = Number(val);
        const last = ops[ops.length - 1];
        if (typeof last === "string") ops[ops.length - 1] = { op: last, args: { [key]: val } };
        else last.args[key] = val;
    } else if (a.startsWith("-") && a !== "-") {
        console.error(`未知选项: ${a}`);
        usage();
        process.exit(1);
    } else {
        ops.push(a);
    }
}

if (ops.length === 0) { usage(); process.exit(1); }

const input = inFile ? readFileSync(inFile) : readFileSync(0);
try {
    const dish = await bake(input, ops);

    if (asJson) {
        let out;
        try { out = dish.get("json"); } catch { out = dish.get("string"); }
        console.log(typeof out === "string" ? out : JSON.stringify(out, null, 2));
        process.exit(0);
    }

    let bytes;
    try { bytes = Buffer.from(dish.get("byteArray")); } catch { bytes = Buffer.from(String(dish.value)); }

    if (outFile) {
        writeFileSync(outFile, bytes);
        console.error(`→ ${outFile} (${bytes.length} 字节)`);
    } else {
        // 看起来是文本就直接打，否则原样输出字节
        const text = bytes.toString("utf8");
        const binary = text.includes("\u0000") || Buffer.from(text, "utf8").length !== bytes.length;
        process.stdout.write(binary ? bytes : text);
    }
} catch (e) {
    console.error(`CyberChef 出错: ${e.message}`);
    process.exit(1);
}
