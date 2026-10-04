"""Optional audio engines, isolated from ScoreBridge's Python environment."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import hashlib
import signal
from datetime import datetime, timezone


ENGINES = {
    "basic_pitch": {
        "package": "basic-pitch", "version": "0.4.0", "module": "basic_pitch",
        "kind": "transcription", "instruments": False, "drums": False,
        "scope": "single instrument, including polyphonic instruments",
    },
    "transkun": {
        "package": "transkun", "version": "2.0.1", "module": "transkun",
        "kind": "transcription", "instruments": False, "drums": False,
        "scope": "piano",
    },
    "yourmt3": {
        "package": "mt3-infer", "version": "0.2.0", "module": "mt3_infer",
        "kind": "transcription", "instruments": True, "drums": True,
        "scope": "multi-instrument mixtures (YourMT3 via MT3-Infer)",
    },
    "demucs": {
        "package": "demucs", "version": "4.1.0", "module": "demucs",
        "kind": "separation", "instruments": False, "drums": False,
        "scope": "audio stems: drums, bass, vocals, other; not orchestral part recovery",
    },
}


def audio_home(cache_dir=""):
    return Path(cache_dir or os.environ.get("SCOREBRIDGE_AUDIO_HOME")
                or Path.home() / ".cache" / "scorebridge" / "audio").expanduser().resolve()


def engine_python(engine, cache_dir=""):
    if engine not in ENGINES:
        raise ValueError("Unknown audio engine: " + str(engine))
    override = os.environ.get("SCOREBRIDGE_AUDIO_" + engine.upper() + "_PYTHON")
    if override:
        return Path(override).expanduser().resolve()
    env = audio_home(cache_dir) / "envs" / engine
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run(command, timeout=60, env=None):
    # Some engines start their own Python child. A timeout must release that
    # model too, rather than leave it consuming memory while fallback starts.
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env, start_new_session=os.name != "nt")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.kill()
        process.communicate()
        raise
    if process.returncode:
        raise ValueError((stderr or stdout)[-4000:] or "Process failed")
    return stdout


def backend_status(engine, cache_dir=""):
    """Check actual imports in the selected interpreter; never downloads weights."""
    spec = ENGINES[engine]
    python = engine_python(engine, cache_dir)
    report = {"engine": engine, **spec, "python": str(python),
              "installed": False, "runtime_verified": False}
    if not python.is_file():
        return {**report, "reason": "isolated runtime not installed"}
    worker = Path(__file__).with_name("worker.py")
    try:
        data = json.loads(_run([str(python), str(worker), "probe", engine], timeout=90))
        proof = audio_home(cache_dir) / "verified" / (engine + ".json")
        if proof.is_file():
            verification = json.loads(proof.read_text(encoding="utf-8"))
            if (verification.get("version") == data.get("version_installed")
                    and verification.get("worker_sha256") == hashlib.sha256(worker.read_bytes()).hexdigest()):
                data.update(runtime_verified=True, last_inference=verification)
        return {**report, **data}
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {**report, "reason": str(exc)}


def audio_backends(cache_dir=""):
    return {"cache_dir": str(audio_home(cache_dir)),
            "engines": [backend_status(engine, cache_dir) for engine in ENGINES]}


def record_inference(engine, version, source_hash, cache_dir=""):
    folder = audio_home(cache_dir) / "verified"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (engine + ".json")).write_text(json.dumps({
        "version": version, "source_sha256": source_hash,
        "worker_sha256": hashlib.sha256(Path(__file__).with_name("worker.py").read_bytes()).hexdigest(),
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "Actual inference and readable output; not accuracy certification",
    }, indent=2), encoding="utf-8")


def _compatible_python(cache_dir=""):
    candidates = [os.environ.get("SCOREBRIDGE_AUDIO_INSTALL_PYTHON", "")]
    if (3, 10) <= sys.version_info[:2] <= (3, 11):
        candidates.append(sys.executable)
    candidates.extend(shutil.which(name) for name in ("python3.11", "python3.10"))
    for candidate in filter(None, candidates):
        try:
            version = json.loads(_run([candidate, "-c", "import sys,json; print(json.dumps(list(sys.version_info[:2])))"]))
            if (3, 10) <= tuple(version) <= (3, 11):
                return candidate
        except (ValueError, OSError, subprocess.SubprocessError):
            continue
    uv = shutil.which("uv")
    if uv:
        env = os.environ.copy()
        env.update(UV_PYTHON_INSTALL_DIR=str(audio_home(cache_dir) / "python"),
                   UV_CACHE_DIR=str(audio_home(cache_dir) / "uv-cache"))
        _run([uv, "python", "install", "3.11", "--no-bin", "--no-registry"], timeout=600, env=env)
        return _run([uv, "python", "find", "3.11", "--managed-python", "--no-project"], env=env).strip()
    raise ValueError("Audio engines need Python 3.10/3.11. Agent can install uv or set SCOREBRIDGE_AUDIO_INSTALL_PYTHON; the core environment is unchanged.")


def install_backend(engine, cache_dir=""):
    """Install only the requested engine. Native tools and user environments stay intact."""
    try:
        if engine not in ENGINES:
            raise ValueError("Unknown audio engine: " + str(engine))
        current = backend_status(engine, cache_dir)
        if current["installed"] and current.get("version_installed") == ENGINES[engine]["version"]:
            return {"status": "installed", "reused": True, **current}
        if os.environ.get("SCOREBRIDGE_AUDIO_" + engine.upper() + "_PYTHON"):
            raise ValueError("The configured external runtime is unusable; fix it or remove the override. It will not be modified.")
        python = engine_python(engine, cache_dir)
        env_dir = python.parent.parent
        env_dir.parent.mkdir(parents=True, exist_ok=True)
        _run([_compatible_python(cache_dir), "-m", "venv", str(env_dir)], timeout=120)
        pip = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
        spec = ENGINES[engine]
        requirement = spec["package"] + "==" + spec["version"]
        if engine == "basic_pitch":
            # Upstream platform defaults pull TensorFlow/CoreML. Use its supported
            # ONNX model with only inference dependencies, in an isolated runtime.
            _run(pip + ["numpy<2", "onnxruntime>=1.17,<2", "librosa>=0.10,<0.12",
                        "pretty-midi>=0.2.10,<0.3", "resampy>=0.2.2,<0.4.3",
                        "scipy", "scikit-learn", "mir-eval", "typing-extensions"], timeout=1800)
            _run(pip + ["--no-deps", requirement], timeout=300)
        else:
            requirements = [requirement]
            if engine in {"yourmt3", "transkun"}:
                # Torchaudio 2.9+ changed the decoding API used by these engines.
                requirements.extend(["torch==2.8.0", "torchaudio==2.8.0"])
            if engine == "yourmt3":
                requirements.extend(["torchvision==0.23.0", "transformers==4.43.4", "numpy<2"])
            if engine == "demucs":
                requirements.append("numpy<2")
            _run(pip + requirements, timeout=1800)
        current = backend_status(engine, cache_dir)
        if not current["installed"]:
            raise ValueError("Installed packages failed their import check: " + current.get("reason", "unknown"))
        (env_dir / "scorebridge-install.json").write_text(
            json.dumps({"engine": engine, "package": requirement, "python": str(python)}, indent=2), encoding="utf-8")
        return {"status": "installed", "reused": False, **current}
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        return {"status": "error", "stage": "audio_install", "engine": engine, "error": str(exc)}


def run_backend(engine, input_path, output_path, cache_dir="", timeout=1800, device="cpu"):
    """The worker runs in a disposable subprocess, releasing model memory on exit."""
    python = engine_python(engine, cache_dir)
    worker = Path(__file__).with_name("worker.py")
    env = dict(os.environ)
    cache = audio_home(cache_dir)
    env["MT3_CHECKPOINT_DIR"] = str(cache / "weights" / "yourmt3")
    env["TORCH_HOME"] = str(cache / "weights" / "torch")
    env["HF_HOME"] = str(cache / "weights" / "huggingface")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _run([str(python), str(worker), "run", engine, str(input_path), str(output), device], timeout=timeout, env=env)
    if not output.is_file():
        raise ValueError("Engine did not produce its result")
    return json.loads(output.read_text(encoding="utf-8"))
