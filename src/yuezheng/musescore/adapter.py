"""Diagnosable MuseScore process adapter."""
from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional
from zipfile import BadZipFile, ZipFile

class MuseScoreError(RuntimeError):
    pass


class MuseScoreBackend:
    """Small backend contract shared by CLI and future MCP adapters."""

    name = "base"

    def status(self) -> dict:
        raise NotImplementedError

    def convert(self, input_path: str, output_path: str) -> dict:
        raise NotImplementedError

@dataclass
class MuseScoreAdapter(MuseScoreBackend):
    executable: Optional[str] = None
    timeout: int = 90
    name: str = "cli"

    def resolve(self) -> Optional[Path]:
        if self.executable:
            explicit = Path(self.executable)
            return explicit if explicit.is_file() else None
        candidates = [self.executable] if self.executable else [os.environ.get("MUSESCORE_BIN")]
        candidates += [shutil.which("mscore"), shutil.which("MuseScore"), "/Applications/MuseScore 4.app/Contents/MacOS/mscore"]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return Path(candidate)
        return None

    def status(self) -> dict:
        exe = self.resolve()
        return {"available": bool(exe), "executable": str(exe) if exe else None, "backend": "cli" if exe else None,
                "hint": None if exe else "Install MuseScore 4 or set MUSESCORE_BIN."}

    def open_score(self, input_path: str) -> dict:
        """Launch MuseScore with an existing score file.

        MuseScore's CLI reliably accepts a score path, while creation and
        Save-As are version-dependent. Keep this operation explicit and return
        the process id so callers can verify the live editor separately.
        """
        src = Path(input_path)
        if not src.is_file():
            raise MuseScoreError(f"Input does not exist: {src}")
        exe = self.resolve()
        if not exe:
            raise MuseScoreError(self.status()["hint"])
        command = [str(exe), str(src.resolve())]
        if sys.platform == "darwin":
            app = next((Path(*exe.parts[:index + 1]) for index, part in enumerate(exe.parts)
                        if part.endswith(".app")), None)
            if app:
                # Send a normal macOS open-document event. Launching the inner
                # binary directly does not reliably open a path in an existing instance.
                command = ["/usr/bin/open", "-a", str(app), str(src.resolve())]
        try:
            process = subprocess.Popen(command,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       env=os.environ.copy())
        except OSError as exc:
            raise MuseScoreError(f"MuseScore could not be launched: {exc}") from exc
        return {"status": "pass", "input_path": str(src.resolve()),
                "executable": str(exe), "pid": process.pid,
                "command": command}

    def launch_score_process(self, input_path: str) -> dict:
        """Start a dedicated MuseScore process for a score and return its real PID."""
        src = Path(input_path)
        if not src.is_file():
            raise MuseScoreError(f"Input does not exist: {src}")
        exe = self.resolve()
        if not exe:
            raise MuseScoreError(self.status()["hint"])
        command = [str(exe), str(src.resolve())]
        if sys.platform == "darwin":
            app = next((Path(*exe.parts[:index + 1]) for index, part in enumerate(exe.parts)
                        if part.endswith(".app")), None)
            if app:
                before = self._running_musescore_pids(exe)
                command = ["/usr/bin/open", "-n", "-a", str(app), str(src.resolve())]
                try:
                    subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=os.environ.copy(), timeout=15)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise MuseScoreError(f"MuseScore could not be launched: {exc}") from exc
                pid = None
                for _ in range(40):
                    created = self._running_musescore_pids(exe) - before
                    if len(created) == 1:
                        pid = created.pop()
                        break
                    time.sleep(0.125)
                if pid is None:
                    raise MuseScoreError("MuseScore launched but its new process could not be identified")
                return {"status": "pass", "input_path": str(src.resolve()),
                        "executable": str(exe), "pid": pid, "command": command,
                        "launch_mode": "dedicated_process"}
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, env=os.environ.copy())
        except OSError as exc:
            raise MuseScoreError(f"MuseScore could not be launched: {exc}") from exc
        return {"status": "pass", "input_path": str(src.resolve()),
                "executable": str(exe), "pid": process.pid, "command": command,
                "launch_mode": "dedicated_process"}

    @staticmethod
    def _running_musescore_pids(executable: Path) -> set[int]:
        try:
            result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                                    text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return set()
        prefix = str(executable)
        found = set()
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) == 2 and fields[0].isdigit() and fields[1].startswith(prefix):
                found.add(int(fields[0]))
        return found

    @staticmethod
    def _valid_output(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        if path.suffix.lower() != ".mscz":
            return True
        try:
            with ZipFile(path) as archive:
                return archive.testzip() is None and any(
                    name.lower().endswith(".mscx") for name in archive.namelist()
                )
        except (BadZipFile, OSError):
            return False

    def convert(self, input_path: str, output_path: str) -> dict:
        src, dst = Path(input_path), Path(output_path)
        if not src.exists():
            raise MuseScoreError(f"Input does not exist: {src}")
        exe = self.resolve()
        if not exe:
            raise MuseScoreError(self.status()["hint"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        # MuseScore's macOS bundle ships only the cocoa Qt platform plugin.
        # Leave platform selection untouched unless the caller explicitly set it.
        # Generate into an empty location: an old valid destination must never
        # turn a failed export into a false success. Publish only verified output.
        with tempfile.TemporaryDirectory(prefix="scorebridge-", dir=dst.parent) as temporary:
            generated = Path(temporary) / dst.name
            try:
                proc = subprocess.run([str(exe), "-o", str(generated), str(src.resolve())], capture_output=True, text=True, timeout=self.timeout, env=env)
            except subprocess.TimeoutExpired as exc:
                raise MuseScoreError(f"MuseScore timed out after {self.timeout}s") from exc
            result = {"command": [str(exe), "-o", str(generated), str(src.resolve())], "returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "output_path": str(dst.resolve())}
            if not self._valid_output(generated):
                detail = proc.stderr[-1000:].strip()
                raise MuseScoreError(f"MuseScore conversion failed (code {proc.returncode}): {detail}")
            if proc.returncode != 0:
                result["warning"] = f"MuseScore exited with code {proc.returncode} after writing a valid output file"
            generated.replace(dst)
            result["output_valid"] = True
            return result
