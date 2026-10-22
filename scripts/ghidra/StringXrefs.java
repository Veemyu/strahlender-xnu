// Lists, per string literal slot (Il2CppDumper address from stringliteral.json), the functions that reference it.
// Script arguments: <output-file> <name>=<address-hex> [<name>=<address-hex> ...]
// The Ghidra address is the Il2CppDumper address + 0x100000.
// @category IL2CPP

import java.io.File;
import java.io.PrintWriter;
import java.util.Set;
import java.util.TreeSet;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class StringXrefs extends GhidraScript {

	private static final long IMAGE_BASE = 0x100000L;

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		File out = new File(args[0]);
		out.getParentFile().mkdirs();
		try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
			for (int i = 1; i < args.length; i++) {
				int eq = args[i].indexOf('=');
				String name = args[i].substring(0, eq);
				long slot = Long.decode(args[i].substring(eq + 1)) + IMAGE_BASE;
				Address a = toAddr(slot);
				Set<String> funcs = new TreeSet<>();
				for (Reference r : getReferencesTo(a)) {
					Function f = getFunctionContaining(r.getFromAddress());
					funcs.add(f == null ? "?@" + r.getFromAddress() : f.getName() + "@" + f.getEntryPoint());
				}
				w.println(name + " " + funcs.size());
				for (String s : funcs) {
					w.println("  " + s);
				}
			}
		}
	}
}
