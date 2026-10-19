// Listet je Funktion (Namens-Regex) die aufrufenden Funktionen (Referenzen vom Typ Aufruf/Datenzeiger).
// Skriptargumente: <Ausgabedatei> <Regex auf Funktionsnamen> [<Regex> ...]
// @category IL2CPP

import java.io.File;
import java.io.PrintWriter;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Pattern;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;

public class CallersOf extends GhidraScript {

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		File out = new File(args[0]);
		out.getParentFile().mkdirs();
		try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
			for (int i = 1; i < args.length; i++) {
				Pattern rx = Pattern.compile(args[i]);
				FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
				while (it.hasNext()) {
					Function f = it.next();
					if (!rx.matcher(f.getName()).find()) {
						continue;
					}
					Set<String> callers = new TreeSet<>();
					for (Reference r : getReferencesTo(f.getEntryPoint())) {
						Function c = getFunctionContaining(r.getFromAddress());
						callers.add(c == null ? "?@" + r.getFromAddress() : c.getName() + "@" + c.getEntryPoint());
					}
					w.println(f.getName() + "@" + f.getEntryPoint() + " " + callers.size());
					for (String s : callers) {
						w.println("  " + s);
					}
				}
			}
		}
	}
}
