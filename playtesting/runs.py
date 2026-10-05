"""Run preparation and provenance. Game data never goes into source control."""
from datetime import datetime, timezone
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
COLORS = ("red", "blue", "tan", "green", "orange", "purple", "teal", "pink")
DATA = Path("Library/Application Support/vcmi")


def copy_snapshot_file(source, destination):
    """Independent files, using APFS copy-on-write where the filesystem allows it."""
    if sys.platform == "darwin":
        clone = getattr(ctypes.CDLL(None, use_errno=True), "clonefile", None)
        if clone is not None:
            clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
            clone.restype = ctypes.c_int
            if clone(os.fsencode(source), os.fsencode(destination), 0) == 0:
                shutil.copystat(source, destination)
                return str(destination)
            error = ctypes.get_errno()
            if error not in (errno.EXDEV, errno.ENOTSUP, errno.EINVAL, errno.ENOSYS):
                raise OSError(error, os.strerror(error), str(destination))
    return shutil.copy2(source, destination)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load(run):
    return json.loads((Path(run) / "manifest.json").read_text(encoding="utf-8"))


def snapshot(directory):
    directory = Path(directory)
    return {str(p.relative_to(directory)): digest(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def absolute(value, base):
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def finite_positive(value, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    if maximum and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")


def prepare(config_path, out):
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("version") != 1:
        raise ValueError("unsupported configuration version")
    base = config_path.parent
    engine = absolute(config["engine"], base)
    profile = absolute(config["profile_template"], base)
    map_resource = config["map_resource"]
    resource = Path(map_resource)
    if resource.is_absolute() or ".." in resource.parts or resource.parts[0] != "Maps":
        raise ValueError("map_resource must be a relative Maps/... path")
    if not engine.is_file() or not (profile / DATA / resource).is_file():
        raise ValueError("engine or fixture map is missing")
    save_resource = config.get('save_resource')
    if save_resource is not None:
        saved = Path(save_resource)
        if (saved.is_absolute() or '..' in saved.parts or not saved.parts
                or saved.parts[0] != 'Saves' or saved.suffix.lower() != '.vsgm1'):
            raise ValueError('save_resource must be a relative Saves/...vsgm1 path')
        if not (profile / DATA / saved).is_file():
            raise ValueError('fixture save is missing')
    if not (profile / DATA / "config/settings.json").is_file():
        raise ValueError("fixture config/settings.json is missing")
    if any(p.is_symlink() for p in profile.rglob("*")):
        raise ValueError("fixture must contain real files, not symlinks to another profile")
    players = config["players"]
    if not players or any(c not in COLORS or not isinstance(ai, str) or not ai for c, ai in players.items()):
        raise ValueError("players must map VCMI colors to AI names")
    if config.get("purpose") not in ("integration", "training", "evaluation") or not config.get("case_id"):
        raise ValueError("case_id and purpose (integration/training/evaluation) are required")
    if "Nullkiller3" in players.values():
        config.setdefault("nk3_mode", "model")
        if config["nk3_mode"] not in ("native", "model"):
            raise ValueError("nk3_mode must be native or model")
    elif "nk3_mode" in config:
        raise ValueError("nk3_mode requires a Nullkiller3 player")
    finite_positive(config["max_seconds"], "max_seconds")
    interval = config.setdefault('review_interval_days', 0)
    if type(interval) is not int or not 0 <= interval <= 365:
        raise ValueError('review_interval_days must be an integer from 0 (off) to 365')
    experience_mode = config.get('experience_mode', 'learn')
    if experience_mode not in ('off', 'read_only', 'learn'):
        raise ValueError('experience_mode must be off, read_only or learn')
    config.setdefault("decision_timeout_seconds", 130)
    finite_positive(config["decision_timeout_seconds"], "decision_timeout_seconds", 130)
    controller = config["controller"]
    if not isinstance(controller, list) or not controller or any(not isinstance(a, str) for a in controller):
        raise ValueError("controller must be an argv array, without a shell")
    controller[0] = str(absolute(controller[0], base))
    if not Path(controller[0]).is_file():
        raise ValueError("controller executable is missing")
    # File arguments are resolved once; record any additional imported sources explicitly.
    for i in range(1, len(controller)):
        candidate = absolute(controller[i], base)
        if candidate.is_file():
            controller[i] = str(candidate)
    sources = {str(absolute(p, base)): digest(absolute(p, base))
               for p in config.get("controller_sources", [])}
    sources.update({a: digest(a) for a in controller if Path(a).is_absolute() and Path(a).is_file()})
    engine_sources = {str(absolute(p, base)): digest(absolute(p, base))
                      for p in config.get("engine_sources", [])}
    refs = {name: absolute(value, base) for name, value in config.get("references", {}).items()}
    if any(name not in ("prompt", "knowledge") or not path.is_file() for name, path in refs.items()):
        raise ValueError("references supports existing prompt and knowledge files")
    out = Path(out).resolve()
    if out == profile or out.is_relative_to(profile) or profile.is_relative_to(out):
        raise ValueError("run and template must be separate directory trees")
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        shutil.copytree(profile, out / "profile", copy_function=copy_snapshot_file)
        (out / "references").mkdir()
        (out / "decisions").mkdir()
        (out / "episodes").mkdir()
        (out / "evidence").mkdir()
        references = {}
        for name, path in refs.items():
            dest = out / "references" / (name + ".md")
            shutil.copyfile(path, dest)
            references[name] = {"path": str(dest.relative_to(out)), "sha256": digest(dest)}
        # Live matches learn; integration keeps its own library. Offline replay
        # consumes the frozen initial baseline without changing live experience.
        library = absolute(config.get('experience_database',str(ROOT / '.build/experience.sqlite3')),base)
        experience = {'mode':experience_mode,'database':str(out / 'experience.sqlite3' if config['purpose'] == 'integration' else library),
                      'baseline':None}
        if experience_mode != 'off' and (config['purpose'] in ('training','evaluation') or experience_mode == 'read_only') and library.is_file():
            snapshot_path = out / 'experience-before.sqlite3'
            with sqlite3.connect(library.as_uri()+'?mode=ro',uri=True) as source, sqlite3.connect(snapshot_path) as target:
                source.backup(target)
            experience['baseline'] = {'path':snapshot_path.name,'sha256':digest(snapshot_path)}
        if experience_mode == 'read_only':
            if experience['baseline'] is None:
                raise ValueError('read_only experience requires an existing lesson library')
            experience['database'] = str(out / experience['baseline']['path'])
        manifest = {
            **config, "run_id": uuid.uuid4().hex, "created_at": now(), "status": "prepared",
            "engine": str(engine), "engine_sha256": digest(engine),
            "engine_sources": engine_sources,
            "controller": controller, "controller_sources": sources, "references": references,
            "experience":experience,
            "map_sha256": digest(out / "profile" / DATA / resource),
            "save_sha256": digest(out / "profile" / DATA / save_resource) if save_resource else None,
            "profile_sha256": snapshot(out / "profile"),
            "engine_pin": json.loads((ROOT / "engine/version.json").read_text()),
            "reference_consumption": "unconfirmed: controller must explicitly use the snapshot paths",
        }
        write_json(out / "manifest.json", manifest)
    except BaseException:
        shutil.rmtree(out)
        raise
    return manifest


def verify(run, check_profile=False):
    run = Path(run)
    manifest = load(run)
    files = {manifest["engine"]: manifest["engine_sha256"], **manifest["engine_sources"],
             **manifest["controller_sources"]}
    for path, expected in files.items():
        if digest(path) != expected:
            raise ValueError(f"source changed since prepare: {path}; prepare a new run")
    for ref in manifest["references"].values():
        if digest(run / ref["path"]) != ref["sha256"]:
            raise ValueError("reference snapshot changed since prepare")
    baseline = manifest.get('experience',{}).get('baseline')
    if baseline and digest(run / baseline['path']) != baseline['sha256']:
        raise ValueError('experience baseline changed since prepare')
    if check_profile and snapshot(run / "profile") != manifest["profile_sha256"]:
        raise ValueError("initial profile changed since prepare; prepare a new run")
    return manifest
