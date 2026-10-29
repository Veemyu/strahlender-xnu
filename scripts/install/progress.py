"""Generator counters shared by shell-based and native installer builds."""
import re


class GeneratorProgress:
    def __init__(self, total):
        self.total = total
        self.completed = set()

    def feed(self, message):
        analysis = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*): analyzing module", message)
        functions = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*): progress (\d+)/(\d+) files (\d+)", message)
        if analysis or functions:
            marker = analysis or functions
            completed, total = (int(functions[2]), int(functions[3])) if functions else (0, 0)
            if completed <= total:
                return dict(id="eh_gen", module=marker[1], phase="emit" if functions else "analyze",
                            unit="functions", completed=completed, total=total,
                            modules_completed=len(self.completed), modules_total=self.total)
        marker = (re.match(r"^([A-Za-z_][A-Za-z_0-9]*): wrote ", message) or
                  re.match(r"^module=([A-Za-z_][A-Za-z_0-9]*)\b", message))
        if marker and marker[1] not in self.completed:
            self.completed.add(marker[1])
            return dict(id="eh_gen", completed=min(len(self.completed), self.total), total=self.total)
        return None
