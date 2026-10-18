// Sucht Instruktionen mit bestimmten Skalar-Operanden und zaehlt Treffer je Funktion.
// Skriptargumente: <kommagetrennte Hexwerte> [Ausgabedatei]
// @category IL2CPP

import java.io.File;
import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;

public class ScanScalars extends GhidraScript {

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		Set<Long> wanted = new HashSet<>();
		for (String s : args[0].split(",")) {
			wanted.add(Long.decode(s.trim()));
		}
		File out = new File(args.length > 1 ? args[1] : "work/ghidra/scan_scalars.txt");
		Map<String, Map<Long, Integer>> hits = new TreeMap<>();
		InstructionIterator it = currentProgram.getListing().getInstructions(true);
		long n = 0;
		while (it.hasNext()) {
			Instruction ins = it.next();
			if ((++n & 0xFFFFF) == 0) {
				monitor.checkCancelled();
			}
			for (int op = 0; op < ins.getNumOperands(); op++) {
				Scalar sc = ins.getScalar(op);
				if (sc != null && wanted.contains(sc.getUnsignedValue())) {
					Function f = getFunctionContaining(ins.getAddress());
					String key = f == null ? "? @" + ins.getAddress() : "0x" + f.getEntryPoint() + " " + f.getName();
					hits.computeIfAbsent(key, k -> new TreeMap<>()).merge(sc.getUnsignedValue(), 1, Integer::sum);
				}
			}
		}
		try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
			for (Map.Entry<String, Map<Long, Integer>> e : hits.entrySet()) {
				StringBuilder sb = new StringBuilder(e.getKey());
				for (Map.Entry<Long, Integer> h : e.getValue().entrySet()) {
					sb.append("  0x").append(Long.toHexString(h.getKey())).append("x").append(h.getValue());
				}
				w.println(sb);
			}
		}
		println("ScanScalars: " + hits.size() + " Funktionen mit Treffern -> " + out);
	}
}
