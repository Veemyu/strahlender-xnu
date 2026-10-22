// Decompiles functions whose name matches <regex> and writes one .c file per class (part before "$$").
// Script arguments: <regex on function names> [output directory, default work/decomp]
// @category IL2CPP

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Pattern;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class ExportDecompiled extends GhidraScript {

	private static final int TIMEOUT_SEC = 60;

	private File repoRoot() {
		if (sourceFile != null) {
			File f = sourceFile.getFile(false);
			if (f != null) {
				File root = f.getAbsoluteFile().getParentFile().getParentFile().getParentFile();
				if (root != null && new File(root, "work").isDirectory()) {
					return root;
				}
			}
		}
		return new File(System.getProperty("user.dir"));
	}

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 1) {
			throw new IllegalArgumentException("Arguments: <regex> [output directory]");
		}
		Pattern rx = Pattern.compile(args[0]);
		File root = repoRoot();
		File outDir = args.length > 1 ? new File(args[1]) : new File(root, "work/decomp");
		if (!outDir.isAbsolute()) {
			outDir = new File(root, outDir.getPath());
		}
		outDir.mkdirs();

		Map<String, List<Function>> byClass = new TreeMap<>();
		FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
		int matched = 0;
		while (it.hasNext()) {
			Function f = it.next();
			String name = f.getName();
			if (!rx.matcher(name).find()) {
				continue;
			}
			int idx = name.indexOf("$$");
			String cls = idx > 0 ? name.substring(0, idx) : "_misc";
			cls = cls.replaceAll("[^A-Za-z0-9_.$-]", "_");
			byClass.computeIfAbsent(cls, k -> new ArrayList<>()).add(f);
			matched++;
		}
		println("ExportDecompiled: " + matched + " functions in " + byClass.size() + " classes match " + rx);

		DecompInterface ifc = new DecompInterface();
		try {
			if (!ifc.openProgram(currentProgram)) {
				throw new IllegalStateException("Decompiler could not be opened: " + ifc.getLastMessage());
			}
			int done = 0, failed = 0;
			long t0 = System.currentTimeMillis();
			for (Map.Entry<String, List<Function>> e : byClass.entrySet()) {
				File out = new File(outDir, e.getKey() + ".c");
				try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
					for (Function f : e.getValue()) {
						monitor.checkCancelled();
						w.println("// 0x" + f.getEntryPoint().toString().replaceFirst("^0+(?=.)", "") + " " + f.getName());
						try {
							DecompileResults res = ifc.decompileFunction(f, TIMEOUT_SEC, monitor);
							if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
								w.println(res.getDecompiledFunction().getC());
							}
							else {
								failed++;
								w.println("// ERROR: " + (res == null ? "no result" : res.getErrorMessage()));
								w.println();
							}
						}
						catch (Exception ex) {
							failed++;
							w.println("// ERROR: " + ex);
							w.println();
						}
						done++;
						if (done % 200 == 0) {
							println("ExportDecompiled: " + done + "/" + matched + " (errors " + failed + "), " +
								(System.currentTimeMillis() - t0) / 1000 + " s");
						}
					}
				}
			}
			println("ExportDecompiled: done, " + done + " functions, " + failed + " errors/timeouts, output: " + outDir);
		}
		finally {
			ifc.dispose();
		}
	}
}
