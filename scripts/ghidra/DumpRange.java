// Gibt das Listing eines Adressbereichs aus (auch ausserhalb von Funktionen).
// Skriptargumente: <Start-Hex> <Ende-Hex> [Ausgabedatei]
// @category IL2CPP

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;

public class DumpRange extends GhidraScript {

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		Address start = toAddr(Long.decode(args[0]));
		Address end = toAddr(Long.decode(args[1]));
		File out = new File(args.length > 2 ? args[2] : "work/ghidra/dump_range.txt");
		try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
			Address a = start;
			while (a.compareTo(end) < 0) {
				Function f = getFunctionAt(a);
				if (f != null) {
					w.println("---- FUNC " + f.getName() + " @" + a);
				}
				CodeUnit cu = currentProgram.getListing().getCodeUnitAt(a);
				if (cu == null) {
					w.println(a + "  <kein Code>");
					a = a.add(4);
					continue;
				}
				w.println(a + "  " + cu);
				a = cu.getMaxAddress().add(1);
			}
		}
	}
}
