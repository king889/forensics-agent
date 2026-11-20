// 把函数反编译成 C，给 headless 用。默认**不**全量反编译。
//
//   ghidra-headless work/gh proj -import lib.so \
//       -postScript DecompileToC.java work/decompiled.c Java_com_app_Native
//
//   ghidra-headless work/gh proj -import lib.so \
//       -postScript DecompileToC.java work/decompiled.c "" 50
//
//   ghidra-headless work/gh proj -import lib.so \
//       -postScript DecompileToC.java work/decompiled.c ALL     # 真的全量，慢
//
// 参数: <输出文件> [函数名子串过滤] [最多反编译几个, 默认 200]
// 不给过滤又不给 ALL 会直接拒绝，避免误触发几万个函数。

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;

import java.io.File;
import java.io.PrintWriter;

public class DecompileToC extends GhidraScript {

    private static final int PER_FUNC_TIMEOUT = 30;   // 单个函数 30s 够了
    private static final int DEFAULT_MAX = 200;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = args.length > 0 ? args[0] : "decompiled.c";
        // 第二个参数写法: 名字 / 名字:上限 / :上限 / -:上限 / ALL / ALL:0
        String spec = args.length > 1 ? args[1].trim() : "";
        String filter = null;
        int max = DEFAULT_MAX;
        boolean all = false;
        boolean maxGiven = false;
        int colon = spec.lastIndexOf(':');
        if (colon >= 0) {
            String num = spec.substring(colon + 1).trim();
            spec = spec.substring(0, colon).trim();
            if (!num.isEmpty()) {
                try {
                    max = Integer.parseInt(num);
                    maxGiven = true;
                } catch (NumberFormatException e) {
                    println("ERROR: 上限要写数字，例如 get_secret:20 或 :50");
                    return;
                }
            }
        }
        if (args.length > 2) {
            try {
                max = Integer.parseInt(args[2].trim());
                maxGiven = true;
            } catch (NumberFormatException e) {
                // 忽略，用前面的
            }
        }
        if ("ALL".equalsIgnoreCase(spec)) {
            all = true;
        } else if (!spec.isEmpty() && !"-".equals(spec)) {
            filter = spec;
        }
        if (max <= 0) {
            max = Integer.MAX_VALUE;
        }

        FunctionManager fm = currentProgram.getFunctionManager();
        int total = fm.getFunctionCount();
        if (filter == null && !all && !maxGiven) {
            println("拒绝全量反编译: 这个程序有 " + total + " 个函数。");
            println("  给函数名子串: -postScript DecompileToC.java out.c 关键字");
            println("  只取前 N 个:  -postScript DecompileToC.java out.c :" + DEFAULT_MAX);
            println("  真的要全量:   -postScript DecompileToC.java out.c ALL:0");
            return;
        }

        DecompInterface di = new DecompInterface();
        di.toggleCCode(true);
        di.toggleSyntaxTree(true);
        if (!di.openProgram(currentProgram)) {
            println("ERROR: 反编译器打不开 " + currentProgram.getName());
            return;
        }

        long t0 = System.currentTimeMillis();
        File out = new File(outPath);
        PrintWriter pw = new PrintWriter(out, "UTF-8");
        int ok = 0, fail = 0, seen = 0;

        for (Function f : fm.getFunctions(true)) {
            if (f.isThunk()) {
                continue;
            }
            if (filter != null && !f.getName().contains(filter)) {
                continue;
            }
            if (ok + fail >= max) {
                println("已到上限 " + max + "，停止（还有更多函数没反编译）");
                break;
            }
            seen++;
            DecompileResults r = di.decompileFunction(f, PER_FUNC_TIMEOUT, monitor);
            if (r != null && r.decompileCompleted()) {
                pw.println("// ======== " + f.getName() + " @ " + f.getEntryPoint() + " ========");
                pw.println(r.getDecompiledFunction().getC());
                ok++;
            } else {
                pw.println("// ---- 反编译失败: " + f.getName() + " @ " + f.getEntryPoint());
                fail++;
            }
            if (seen % 50 == 0) {
                println("  ... " + seen + " 个已处理");
            }
        }
        pw.close();
        di.dispose();
        long ms = System.currentTimeMillis() - t0;
        println("反编译完成: " + ok + " 成功 / " + fail + " 失败，程序共 " + total
                + " 个函数，用时 " + (ms / 1000) + "s -> " + out.getAbsolutePath());
    }
}
