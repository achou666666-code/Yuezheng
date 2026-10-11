from dataclasses import dataclass
from pathlib import Path
import os, shutil, subprocess
from typing import Optional

@dataclass
class OMRAdapter:
    executable: Optional[str] = None

    def resolve(self):
        if self.executable:
            candidates = [self.executable]
        else:
            candidates = [
                os.environ.get("AUDIVERIS_BIN"),
                shutil.which("audiveris"),
                shutil.which("Audiveris"),
                "/Applications/Audiveris.app/Contents/MacOS/Audiveris",
                str(Path.home() / "Applications/Audiveris.app/Contents/MacOS/Audiveris"),
            ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return path
        return None

    def status(self):
        executable = self.resolve()
        return {"available": bool(executable), "executable": str(executable) if executable else None,
                "engine": "audiveris" if executable else None,
                "hint": None if executable else "Install Audiveris and set AUDIVERIS_BIN to enable image/PDF OMR."}

    def run(self, input_path: str, output_dir: str):
        executable = self.resolve()
        if not executable: return {"status": "error", **self.status()}
        source, destination = Path(input_path), Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run([str(executable), "-batch", "-export", "-output", str(destination), str(source)], capture_output=True, text=True)
        return {"status": "pass" if proc.returncode == 0 else "error", "output_dir": str(destination.resolve()), "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:], "returncode": proc.returncode}
