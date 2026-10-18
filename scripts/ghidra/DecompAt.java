// Legt (nur im Speicher, mit -readOnly) Funktionen an Adressen an und dekompiliert sie.
// Skriptargumente: <Ausgabedatei> <Adresse-Hex> [<Adresse-Hex> ...]
// @category IL2CPP

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class DecompAt extends GhidraScript {

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		File out = new File(args[0]);
		out.getParentFile().mkdirs();
		DecompInterface ifc = new DecompInterface();
		ifc.openProgram(currentProgram);
		try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
			for (int i = 1; i < args.length; i++) {
				Address a = toAddr(Long.decode(args[i]));
				Function f = getFunctionAt(a);
				if (f == null) {
					disassemble(a);
					f = createFunction(a, "adhoc_" + a);
				}
				w.println("// " + a + " " + (f == null ? "KEINE FUNKTION" : f.getName() + " body=" + f.getBody().getNumAddresses()));
				if (f != null) {
					DecompileResults res = ifc.decompileFunction(f, 120, monitor);
					w.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// FEHLER " + res.getErrorMessage());
				}
			}
		}
		finally {
			ifc.dispose();
		}
	}
}
