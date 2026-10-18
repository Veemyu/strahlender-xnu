// Legt alle IL2CPP-ScriptMethod-Adressen als benannte Funktionen an und startet die Autoanalyse.
// Optionale Skriptargumente: [script.json] [Reportdatei]
// @category IL2CPP

import java.io.File;
import java.io.FileReader;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonToken;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class SeedIl2Cpp extends GhidraScript {

	private static final long IMAGE_BASE = 0x100000L;
	private static final int MAX_LOGGED_ERRORS = 200;

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

	private static String sanitize(String name) {
		StringBuilder sb = new StringBuilder(name.length());
		for (int i = 0; i < name.length(); i++) {
			char c = name.charAt(i);
			boolean ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
				c == '_' || c == '$';
			sb.append(ok ? c : '_');
		}
		return sb.length() == 0 ? "_" : sb.toString();
	}

	@Override
	protected void run() throws Exception {
		File root = repoRoot();
		String[] args = getScriptArgs();
		File json = args.length > 0 ? new File(args[0]) : new File(root, "work/il2cpp/script.json");
		File reportFile = args.length > 1 ? new File(args[1]) : new File(root, "work/ghidra/seed_report.txt");
		reportFile.getParentFile().mkdirs();

		long t0 = System.currentTimeMillis();
		List<String> errors = new ArrayList<>();
		int total = 0, created = 0, renamed = 0, skipped = 0, failed = 0;
		Set<String> usedNames = new HashSet<>();

		setAnalysisOption(currentProgram, "GCC Exception Handlers", "false");

		println("SeedIl2Cpp: lese " + json);
		try (JsonReader r = new JsonReader(new FileReader(json))) {
			r.beginObject();
			while (r.hasNext()) {
				String key = r.nextName();
				if (!key.equals("ScriptMethod")) {
					r.skipValue();
					continue;
				}
				r.beginArray();
				while (r.hasNext()) {
					monitor.checkCancelled();
					long addrVal = -1;
					String name = null;
					r.beginObject();
					while (r.hasNext()) {
						String f = r.nextName();
						if (f.equals("Address") && r.peek() == JsonToken.NUMBER) {
							addrVal = r.nextLong();
						}
						else if (f.equals("Name") && r.peek() == JsonToken.STRING) {
							name = r.nextString();
						}
						else {
							r.skipValue();
						}
					}
					r.endObject();
					total++;

					try {
						if (name == null || addrVal < 0) {
							throw new IllegalStateException("Eintrag unvollstaendig");
						}
						Address addr = toAddr(addrVal + IMAGE_BASE);
						String clean = sanitize(name);
						if (!usedNames.add(clean)) {
							clean = clean + "_" + Long.toHexString(addrVal + IMAGE_BASE);
							while (!usedNames.add(clean)) {
								clean = clean + "_";
							}
						}

						Function fn = getFunctionAt(addr);
						if (fn != null) {
							if (!fn.getName().equals(clean) && fn.getSymbol().getSource() == SourceType.DEFAULT) {
								fn.setName(clean, SourceType.IMPORTED);
								renamed++;
							}
							else {
								skipped++;
							}
						}
						else {
							if (getInstructionAt(addr) == null) {
								disassemble(addr);
							}
							fn = createFunction(addr, clean);
							if (fn == null) {
								throw new IllegalStateException("createFunction lieferte null");
							}
							created++;
						}
					}
					catch (Exception e) {
						failed++;
						if (errors.size() < MAX_LOGGED_ERRORS) {
							errors.add("#" + total + " 0x" + Long.toHexString(addrVal + IMAGE_BASE) + " " + name + ": " + e);
						}
					}

					if (total % 5000 == 0) {
						println(String.format("SeedIl2Cpp: %d verarbeitet (neu %d, umbenannt %d, uebersprungen %d, Fehler %d), %d s",
							total, created, renamed, skipped, failed, (System.currentTimeMillis() - t0) / 1000));
					}
				}
				r.endArray();
			}
			r.endObject();
		}

		long t1 = System.currentTimeMillis();
		println(String.format("SeedIl2Cpp: Seeding fertig: gesamt %d, neu %d, umbenannt %d, uebersprungen %d, Fehler %d (%d s)",
			total, created, renamed, skipped, failed, (t1 - t0) / 1000));
		writeReport(reportFile, total, created, renamed, skipped, failed, errors, (t1 - t0) / 1000, -1, -1, "Seeding fertig, Analyse laeuft");

		println("SeedIl2Cpp: starte Autoanalyse (GCC Exception Handlers aus)");
		analyzeAll(currentProgram);
		long t2 = System.currentTimeMillis();
		int funcs = currentProgram.getFunctionManager().getFunctionCount();
		println("SeedIl2Cpp: Autoanalyse fertig nach " + (t2 - t1) / 1000 + " s, Funktionen gesamt: " + funcs);
		writeReport(reportFile, total, created, renamed, skipped, failed, errors, (t1 - t0) / 1000, (t2 - t1) / 1000, funcs, "fertig");
	}

	private void writeReport(File f, int total, int created, int renamed, int skipped, int failed,
			List<String> errors, long seedSec, long analysisSec, int funcs, String phase) throws Exception {
		try (PrintWriter w = new PrintWriter(f, "UTF-8")) {
			w.println("SeedIl2Cpp Report (" + phase + ")");
			w.println("Programm: " + currentProgram.getName());
			w.println("ScriptMethod-Eintraege: " + total);
			w.println("neu angelegt: " + created);
			w.println("umbenannt (Default-Name): " + renamed);
			w.println("uebersprungen (existierte): " + skipped);
			w.println("Fehler: " + failed);
			w.println("Seeding-Dauer s: " + seedSec);
			if (analysisSec >= 0) {
				w.println("Analyse-Dauer s: " + analysisSec);
				w.println("Funktionen gesamt: " + funcs);
			}
			w.println();
			w.println("Fehler (max. " + MAX_LOGGED_ERRORS + "):");
			for (String e : errors) {
				w.println(e);
			}
		}
	}
}
