"""Prepare, stage and release the accepted API using the existing AWS stack.

Preparation uses a separate Git index. AWS secrets stay in private local files.
Release operations never migrate the database, seed evidence, sign origin
reviews, or change models. Review signing is a separate operator command.
"""
from __future__ import annotations

import argparse
import copy
from hashlib import sha256
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from uuid import uuid4

VERSION = "phase7-aws-vercel-release-v1"
GIT_FOLDER = "tools/phase7_release_v1"
API = "explainable-news-verifier-prod-api-1"
POSTGRES = "explainable-news-verifier-prod-postgres-1"
STORE_TARGET = "/run/verifier-origin-review"
CALIBRATION = "data/metadata/fever_nli_calibration_config.json"
CAL_SHA = "cc72cf72a9e58d9555c22cb52f9f9d3038deb451fca09e41037e846bf8821a5c"
MIGRATION = "f13f2d8gin20261024"
BASE_HEAD = "01777cfc367f5dfc8d56ecfe10c1c828714d6c6e"
OID = re.compile(r"[a-f0-9]{40}(?:[a-f0-9]{24})?\Z")
SENSITIVE = re.compile(r"(^|/)(\.env(?:\.[^/]*)?|trust\.json|[^/]+\.(pem|key|p12|pfx))$", re.I)
DOCKER = ["sudo", "-n", "docker"]


class ReleaseError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise ReleaseError(code)


def normalize(raw):
    return raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode()


def fingerprint(raw):
    return sha256(raw).hexdigest()


def checked(root, relative):
    p = PurePosixPath(relative)
    require(relative and not p.is_absolute() and ".." not in p.parts
            and "\\" not in relative and ":" not in relative, "UNSAFE_PATH")
    root = root.resolve()
    path = root
    for part in p.parts:
        path = path / part
        require(not path.is_symlink(), "SYMLINK_REFUSED")
    require(path.resolve().is_relative_to(root), "PATH_OUTSIDE_ROOT")
    return path


def read(root, relative, maximum=2_000_000):
    p = checked(root, relative)
    require(p.is_file() and p.stat().st_size <= maximum, "SOURCE_UNAVAILABLE")
    raw = p.read_bytes()
    require(len(raw) <= maximum, "SOURCE_TOO_LARGE")
    return raw


def run(args, *, data=None, env=None, cwd=None, timeout=40, code="COMMAND_FAILED"):
    try:
        p = subprocess.run([str(x) for x in args], input=data, capture_output=True,
                           env=env, cwd=cwd, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise ReleaseError(code) from None
    # Never print subprocess stderr: configuration tools can include credentials.
    require(p.returncode == 0 and len(p.stdout) <= 24_000_000, code)
    return p.stdout


def git(repo, *args, data=None, index=None, timeout=40):
    env = dict(os.environ) | {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return run(["git", "--no-optional-locks", "-C", repo, *args],
               data=data, env=env, timeout=timeout, code="GIT_OPERATION_FAILED")


def write_json(path, value, *, exclusive=False):
    require(not path.is_symlink(), "REPORT_SYMLINK_REFUSED")
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if exclusive else "wb"
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with path.open(mode) as f:
        if os.name == "posix":
            os.fchmod(f.fileno(), 0o600)
        f.write(raw)


def package_manifest(folder):
    checks = json.loads(read(folder, "package_checksums.json"))
    require(type(checks) is dict and checks, "PACKAGE_MANIFEST_INVALID")
    for name, digest in checks.items():
        require(fingerprint(read(folder, name)) == digest, "PACKAGE_FILE_CHANGED")
    m = json.loads(read(folder, "release_manifest.json"))
    validate_manifest(m)
    return m


def validate_manifest(m):
    require(m.get("version") == VERSION and len(m.get("source_checksums", {})) == 317,
            "ACCEPTED_MANIFEST_INVALID")
    require(m.get("accepted_phase6", {}).get("operation_id") ==
            "877a64ca8c5d4b989bdaeb0e608299a2", "ACCEPTED_RECEIPT_MISMATCH")
    require(m["accepted_phase6"].get("receipt_sha256") ==
            "1fe31661575598d8daf25a0355bdab8f8516343b250754071417097e3c96f7b2",
            "ACCEPTED_RECEIPT_MISMATCH")
    extras = {"infra/docker/api/Dockerfile", "pyproject.toml", "uv.lock",
              "tools/reporting_origin_review.py", "docs/TRUSTED_REPORTING_ORIGIN_REVIEWS.md",
              "docs/REVIEWED_CLAIM_CORROBORATION.md"}
    for name, digest in m["source_checksums"].items():
        checked(Path.cwd(), name)
        require((name in extras or name.startswith(("apps/api/", "apps/web/", "ml/", "tests/")))
                and not set(PurePosixPath(name).parts) & {".git", "node_modules", "__pycache__"}
                and not SENSITIVE.search(name) and re.fullmatch(r"[a-f0-9]{64}", digest),
                "UNSAFE_SOURCE_MANIFEST")
    return m


def validated_sources(repo, m):
    result = {}
    for name, digest in sorted(m["source_checksums"].items()):
        raw = normalize(read(repo, name))
        require(fingerprint(raw) == digest, "APPLICATION_SOURCE_CHANGED:" + name)
        result[name] = raw
    return result


def docker(*args, data=None, timeout=40):
    return run([*DOCKER, *args], data=data, timeout=timeout, code="DOCKER_COMMAND_FAILED")


def inspect_container(name):
    result = json.loads(docker("inspect", name))
    require(type(result) is list and len(result) == 1, "CONTAINER_UNAVAILABLE")
    return result[0]


def inspect_image(name):
    result = json.loads(docker("image", "inspect", name))
    require(type(result) is list and len(result) == 1, "IMAGE_UNAVAILABLE")
    return result[0]


def environment(values):
    result = {}
    for entry in values or []:
        key, sep, value = entry.partition("=")
        require(sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                and key not in result and "\n" not in value and "\r" not in value,
                "UNSUPPORTED_CONTAINER_ENVIRONMENT")
        result[key] = value
    return result


def service_environment(model, image):
    result = environment(image.get("Config", {}).get("Env"))
    for key, value in model.get("environment", {}).items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = str(value).lower() if isinstance(value, bool) else str(value)
    return result


def actual_mounts(container):
    result = {}
    for m in container.get("Mounts", []):
        require(m["Type"] in {"bind", "volume"}, "UNSUPPORTED_MOUNT_TYPE")
        source = m["Name"] if m["Type"] == "volume" else m["Source"]
        require(not any(c in source + m["Destination"] for c in (",", "\n", "\r")),
                "UNSUPPORTED_MOUNT_PATH")
        require(m["Destination"] not in result, "DUPLICATE_MOUNT_TARGET")
        result[m["Destination"]] = {
            "type": m["Type"], "source": source, "read_only": not m["RW"]}
    return result


def model_mounts(model):
    result = {}
    for m in model["services"]["api"].get("volumes", []):
        require(isinstance(m, dict) and m.get("type") in {"bind", "volume"},
                "COMPOSE_MOUNT_UNRESOLVED")
        source = m["source"]
        if m["type"] == "volume":
            source = model.get("volumes", {}).get(source, {}).get("name", source)
        result[m["target"]] = {"type": m["type"], "source": source,
                               "read_only": m.get("read_only", False)}
    return result


def argv(value):
    return shlex.split(value) if isinstance(value, str) else value


def vector(value):
    value = argv(value)
    require(value is None or isinstance(value, (list, tuple))
            and all(type(x) is str for x in value), "INVALID_STARTUP_VECTOR")
    return list(value or [])


def process_spec(cfg):
    return {"argv": vector(cfg.get("Entrypoint")) + vector(cfg.get("Cmd")),
            "user": str(cfg.get("User") or ""),
            "working_dir": str(cfg.get("WorkingDir") or "")}


def inherited_field(service, field, default, key):
    value = service.get(field)
    return default.get(key) if value is None or value == "" else value


def effective_process(service, default):
    entry = service.get("entrypoint")
    command = service.get("command")
    # Compose null inherits; an explicitly empty command clears the image CMD.
    # Any non-null entrypoint also suppresses an inherited image CMD.
    return process_spec({
        "Entrypoint": default.get("Entrypoint") if entry is None else entry,
        "Cmd": (default.get("Cmd") if entry is None else []) if command is None else command,
        "User": inherited_field(service, "user", default, "User"),
        "WorkingDir": inherited_field(service, "working_dir", default, "WorkingDir")})


def process_fingerprint(cfg):
    return fingerprint(json.dumps(process_spec(cfg), sort_keys=True).encode())


def startup_override(api):
    cfg = api["Config"]
    return {"services": {"api": {
        "entrypoint": vector(cfg.get("Entrypoint")),
        "command": vector(cfg.get("Cmd"))}}}


def validate_base(model, api, image, *, check_process=True):
    service, cfg, default = model["services"]["api"], api["Config"], image["Config"]
    require(service.get("image") == cfg.get("Image"), "COMPOSE_IMAGE_DIFFERS")
    require(service_environment(service, image) == environment(cfg.get("Env")),
            "COMPOSE_ENVIRONMENT_DIFFERS")
    require(model_mounts(model) == actual_mounts(api), "COMPOSE_MOUNTS_DIFFER")
    require(str(inherited_field(service, "user", default, "User") or "")
            == str(cfg.get("User") or ""), "COMPOSE_USER_DIFFERS")
    require(str(inherited_field(service, "working_dir", default, "WorkingDir") or "")
            == str(cfg.get("WorkingDir") or ""), "COMPOSE_WORKING_DIR_DIFFERS")
    if check_process:
        require(effective_process(service, default) == process_spec(cfg),
                "COMPOSE_COMMAND_DIFFERS")


def compose_diagnostics(model, api, image):
    service = model["services"]["api"]
    checks = {"image_matches": service.get("image") == api["Config"].get("Image"),
              "command_is_null": service.get("command") is None,
              "entrypoint_is_null": service.get("entrypoint") is None}
    for key, check in (
        ("environment_matches", lambda: service_environment(service, image)
         == environment(api["Config"].get("Env"))),
        ("mounts_match", lambda: model_mounts(model) == actual_mounts(api)),
        ("effective_process_matches", lambda: effective_process(service, image["Config"])
         == process_spec(api["Config"]))):
        try:
            checks[key] = check()
        except (ReleaseError, ValueError, KeyError, TypeError):
            checks[key] = None
    return checks


def compose_config(prefix):
    value = json.loads(run([*prefix, "config", "--format", "json"],
                           code="COMPOSE_CONFIG_UNAVAILABLE"))
    require(type(value) is dict and "api" in value.get("services", {}),
            "API_COMPOSE_SERVICE_UNAVAILABLE")
    return value


def compose_base(repo, api, image, *, pin_running_process=False):
    labels = api["Config"].get("Labels") or {}
    project = labels.get("com.docker.compose.project", "")
    require(re.fullmatch(r"[a-z0-9][a-z0-9_-]+", project), "COMPOSE_PROJECT_UNAVAILABLE")
    recorded_workdir = labels.get("com.docker.compose.project.working_dir")
    require(type(recorded_workdir) is str and Path(recorded_workdir).is_absolute(),
            "COMPOSE_WORKING_DIRECTORY_UNAVAILABLE")
    workdir = Path(recorded_workdir)
    require(workdir.is_dir() and not workdir.is_symlink(),
            "COMPOSE_WORKING_DIRECTORY_UNAVAILABLE")
    files = labels.get("com.docker.compose.project.config_files", "").split(",")
    require(len(files) == 5 and all(Path(p).is_absolute() and Path(p).is_file()
                                   and not Path(p).is_symlink() for p in files),
            "EXPECTED_FIVE_AWS_COMPOSE_FILES_REQUIRED")
    require([Path(p).name for p in files[:4]] ==
            ["compose.prod.yml", "compose.aws.yml", "compose.aws.test.yml",
             "compose.aws.index.yml"]
            and Path(files[4]).name == "phase13f-01777cf-api-runtime.yml",
            "AWS_COMPOSE_CHAIN_CHANGED")
    prefix = [*DOCKER, "compose", "--project-name", project,
              "--project-directory", str(workdir)]
    named = labels.get("com.docker.compose.project.environment_file")
    choices = []
    if named:
        choices.append([str(Path(p).resolve()) for p in named.split(",")])
    choices += [[str(repo / ".env.production")], [str(repo / ".env")], []]
    failures = set()
    attempts = []
    for selected in choices:
        if any(not Path(p).is_file() or Path(p).is_symlink() for p in selected):
            continue
        args = prefix[:]
        for p in selected:
            args += ["--env-file", p]
        for p in files:
            args += ["-f", p]
        try:
            model = compose_config(args)
            attempts.append(compose_diagnostics(model, api, image))
            validate_base(model, api, image, check_process=not pin_running_process)
            return args, model, files + selected, project
        except ReleaseError as error:
            # Field names only; never export resolved environment values.
            failures.add(str(error) if re.fullmatch(r"[A-Z_]+", str(error))
                         else "COMPOSE_MODEL_INVALID")
            continue
        except (KeyError, TypeError, ValueError):
            failures.add("COMPOSE_MODEL_INVALID")
            continue
    print("COMPOSE_PREFLIGHT_DIAGNOSTICS=" + json.dumps(attempts, separators=(",", ":")),
          flush=True)
    raise ReleaseError("COMPOSE_BASE_DOES_NOT_MATCH_RUNNING_API:"
                       + ",".join(sorted(failures)))


def escape_compose(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape_compose(x) for x in value]
    if isinstance(value, dict):
        return {k: escape_compose(v) for k, v in value.items()}
    return value


def validate_override(base, changed, image, store):
    expected = copy.deepcopy(base)
    service = expected["services"]["api"]
    service["image"] = image
    service.setdefault("environment", {}).update(
        {"ARTICLE_VERIFICATION_ENABLED": "true", "ORIGIN_REVIEW_STORE": STORE_TARGET})
    require(STORE_TARGET not in model_mounts(base), "REVIEW_STORE_MOUNT_ALREADY_PRESENT")
    service.setdefault("volumes", []).append(
        {"type": "bind", "source": str(store), "target": STORE_TARGET,
         "read_only": True, "bind": {"create_host_path": False}})
    service["volumes"] = sorted(service["volumes"], key=lambda x: x["target"])
    actual = copy.deepcopy(changed)
    actual["services"]["api"]["volumes"] = sorted(
        actual["services"]["api"].get("volumes", []), key=lambda x: x["target"])
    # Compose versions can omit a false/empty bind option in canonical JSON.
    # Creating a missing private key directory must remain disabled.
    for value in (expected, actual):
        selected = [v for v in value["services"]["api"]["volumes"]
                    if v["target"] == STORE_TARGET]
        require(len(selected) == 1, "REVIEW_STORE_MOUNT_MISSING")
        options = selected[0].pop("bind", {})
        require(set(options) <= {"create_host_path"}
                and options.get("create_host_path", False) is False,
                "PRIVATE_STORE_AUTO_CREATION_REFUSED")
    require(actual == expected, "UNEXPECTED_COMPOSE_CHANGE")


def private_home():
    root = checked(Path.home(), ".local/share/explainable-news-verifier/phase7-releases")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(root.stat().st_uid == os.getuid(), "PRIVATE_RELEASE_DIRECTORY_OWNER_DIFFERS")
    root.chmod(0o700)
    return root


def load_commit_manifest(repo, commit):
    require(OID.fullmatch(commit), "FULL_RELEASE_COMMIT_REQUIRED")
    parents = git(repo, "rev-list", "--parents", "-n", "1", commit).decode().split()
    require(parents == [commit, BASE_HEAD], "UNEXPECTED_RELEASE_COMMIT_PARENT")
    m = json.loads(git(repo, "show", commit + ":" + GIT_FOLDER + "/release_manifest.json"))
    validate_manifest(m)
    own = normalize(Path(__file__).read_bytes())
    require(own == normalize(git(repo, "show", commit + ":" + GIT_FOLDER + "/release_tool.py")),
            "BOOTSTRAP_DOES_NOT_MATCH_PINNED_COMMIT")
    for name, digest in m["source_checksums"].items():
        require(fingerprint(normalize(git(repo, "show", commit + ":" + name))) == digest,
                "RELEASE_SOURCE_MISMATCH:" + name)
    return m


def extract_build(repo, commit, root, m):
    roots = ["apps/api", "ml", "pyproject.toml", "uv.lock",
             "infra/docker/api/Dockerfile", "tools/reporting_origin_review.py"]
    raw = git(repo, "archive", "--format=tar", commit, *roots)
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for entry in archive:
            if entry.isdir():
                continue
            require(entry.isfile() and not SENSITIVE.search(entry.name)
                    and entry.size <= 2_000_000, "UNSAFE_RELEASE_ARCHIVE_ENTRY")
            total += entry.size
            require(total <= 20_000_000, "RELEASE_ARCHIVE_TOO_LARGE")
            path = checked(root, entry.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            body = archive.extractfile(entry).read()
            require(len(body) == entry.size, "TRUNCATED_RELEASE_ARCHIVE")
            path.write_bytes(body)
    for name, digest in m["source_checksums"].items():
        if any(name == p or name.startswith(p + "/") for p in roots):
            require(fingerprint(normalize(read(root, name))) == digest,
                    "EXTRACTED_SOURCE_MISMATCH")


def validate_running_sources(repo, name):
    names = [n.decode() for n in git(repo, "ls-tree", "-r", "--name-only",
                                     BASE_HEAD, "--", "apps/api", "ml").splitlines()
             if n.endswith(b".py")]
    require(names and all(n.startswith(("apps/api/", "ml/")) and not SENSITIVE.search(n)
                          for n in names), "BASE_RUNTIME_SOURCE_LIST_INVALID")
    expected = {n: fingerprint(normalize(git(repo, "show", BASE_HEAD + ":" + n)))
                for n in names}
    code = (
        "import sys,json,hashlib; from pathlib import Path\n"
        "def digest(name):\n"
        " p=Path('/app')/name\n"
        " if not p.is_file(): return None\n"
        " raw=p.read_bytes().decode('utf-8-sig').replace('\\r\\n','\\n').replace('\\r','\\n').encode()\n"
        " return hashlib.sha256(raw).hexdigest()\n"
        "print(json.dumps({n:digest(n) for n in json.load(sys.stdin)}))\n"
    )
    actual = json.loads(docker("exec", "-i", name, "python", "-c", code,
                                data=json.dumps(names).encode()))
    require(actual == expected, "RUNNING_API_SOURCE_DIFFERS_FROM_BASE_COMMIT")
    return len(names)


def long_run(args, log, label, *, cwd=None, timeout=1800):
    require(not log.is_symlink(), "PRIVATE_LOG_SYMLINK_REFUSED")
    with log.open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        try:
            p = subprocess.Popen([str(x) for x in args], cwd=cwd,
                                 stdout=output, stderr=subprocess.STDOUT)
        except OSError:
            raise ReleaseError(label + "_COULD_NOT_START") from None
        started = time.monotonic()
        try:
            while True:
                try:
                    code = p.wait(timeout=20)
                    require(code == 0, label + "_FAILED")
                    return
                except subprocess.TimeoutExpired:
                    print(label + "_RUNNING", flush=True)
                    require(time.monotonic() - started < timeout, label + "_TIMED_OUT")
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()


def migration():
    shell = ('PGOPTIONS="-c default_transaction_read_only=on '
             '-c statement_timeout=5000 -c lock_timeout=2000" '
             'psql -X -A -t -w -U "$' '{POSTGRES_USER:-postgres}" '
             '-d "$' '{POSTGRES_DB:-$' '{POSTGRES_USER:-postgres}}" '
             '-v ON_ERROR_STOP=1 -c "$1"')
    result = docker("exec", POSTGRES, "sh", "-c", shell, "sh",
                    "SELECT version_num FROM alembic_version;").decode().strip()
    require(result == MIGRATION, "DATABASE_REVISION_DIFFERS")
    return result


def mount_args(mounts):
    args = []
    for target, m in mounts.items():
        value = f"type={m['type']},src={m['source']},dst={target}"
        if m["read_only"]:
            value += ",readonly"
        args += ["--mount", value]
    return args


def ensure_store(image, store):
    require(not store.is_symlink(), "PRIVATE_REVIEW_STORE_SYMLINK_REFUSED")
    require(not any((p / ".git").exists() for p in store.parents),
            "REVIEW_STORE_INSIDE_GIT_REFUSED")
    if not store.exists():
        store.mkdir(mode=0o700)
        code = (
            "import os,json; from pathlib import Path; "
            "from apps.api.services.trusted_reporting_review import init_store; "
            "p=Path('/origin-review'); k=init_store(p,'aleem.operator'); "
            "items=[p]+list(p.rglob('*')); "
            "[(os.chown(x,10001,10001),os.chmod(x,0o700 if x.is_dir() else 0o600)) for x in items]; "
            "print(json.dumps({'initialized':True,'key_id':k}))"
        )
        result = json.loads(docker("run", "--rm", "--network", "none", "--read-only",
            "--user", "0:0", "--entrypoint", "python",
            "--mount", f"type=bind,src={store},dst=/origin-review", image, "-c", code))
        require(result.get("initialized") is True, "REVIEW_STORE_INITIALIZATION_FAILED")
    require(store.stat().st_uid == 10001 and store.stat().st_mode & 0o077 == 0,
            "PRIVATE_REVIEW_STORE_PERMISSIONS_DIFFER")
    code = (
        "import json; from pathlib import Path; "
        "from apps.api.services.trusted_reporting_review import registry; "
        "p=Path('/origin-review'); r=registry(p); "
        "print(json.dumps({'valid':True,'active_reviewers':sum(x['active'] for x in r['reviewers'].values())}))"
    )
    result = json.loads(docker("run", "--rm", "--network", "none", "--read-only",
        "--user", "10001:10001", "--entrypoint", "python",
        "--mount", f"type=bind,src={store},dst=/origin-review,readonly",
        image, "-c", code))
    require(result.get("valid") is True and result.get("active_reviewers", 0) >= 1,
            "REVIEW_STORE_NOT_READABLE_BY_API")


def probe(name):
    code = (
        "import json,urllib.request,urllib.error; "
        "r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready',timeout=8)); "
        "assert r.get('ready') is True and r.get('checks')=={'postgres':'ok','redis':'ok','qdrant':'ok'}; "
        "print(json.dumps({'ready':True,'checks':r['checks']}))"
    )
    ready = json.loads(docker("exec", name, "python", "-c", code, timeout=20))
    code = (
        "import json,urllib.request,urllib.error\n"
        "request=urllib.request.Request('http://127.0.0.1:8000/api/v1/article/verify',"
        "data=json.dumps({'kind':'pasted','text':'Chandrayaan-3 landed on the Moon. '+"
        "'This background paragraph explains the scope of this local check without adding independent evidence.'}).encode(),"
        "headers={'Content-Type':'application/json'},method='POST')\n"
        "try: urllib.request.urlopen(request,timeout=8)\n"
        "except urllib.error.HTTPError as e:\n"
        " assert e.code==401\n"
        " print(json.dumps({'unauthenticated_article_rejected':True}))\n"
        "else: raise SystemExit(1)\n"
    )
    auth = json.loads(docker("exec", name, "python", "-c", code, timeout=20))
    require(ready.get("ready") is True and auth.get("unauthenticated_article_rejected") is True,
            "API_READINESS_OR_AUTH_CHECK_FAILED")
    return ready | auth


def wait_ready(name, *, seconds=180):
    started = time.monotonic()
    while True:
        try:
            return probe(name)
        except (ReleaseError, KeyError, ValueError, TypeError):
            require(time.monotonic() - started < seconds, "API_READINESS_TIMED_OUT")
            print("WAITING_FOR_API_READINESS", flush=True)
            time.sleep(3)


def store_probe(name):
    code = (
        "import os,json; from pathlib import Path; "
        "from apps.api.services.trusted_reporting_review import registry; "
        "p=Path(os.environ['ORIGIN_REVIEW_STORE']); r=registry(p); "
        "assert p.is_absolute() and p.stat().st_mode & 0o077==0; "
        "assert any(x['active'] for x in r['reviewers'].values()); "
        "print(json.dumps({'private_store_readable':True}))"
    )
    result = json.loads(docker("exec", name, "python", "-c", code))
    require(result.get("private_store_readable") is True, "API_CANNOT_READ_PRIVATE_REVIEW_STORE")
    return result


def remove_candidate(state):
    name = state.get("candidate")
    if not name:
        return
    api = inspect_container(name)
    require(api["Config"].get("Labels", {}).get("verifier.phase7.operation")
            == state["operation"], "CANDIDATE_OWNERSHIP_DIFFERS")
    require(not state.get("candidate_id") or api["Id"] == state["candidate_id"],
            "CANDIDATE_IDENTITY_CHANGED")
    docker("rm", "--force", name, timeout=60)


def public_result(state, status, **extra):
    result = {
        "status": status, "release_commit": state["commit"],
        "operation": state["operation"], "application_files_matched": 317,
        "database_revision": state["database_revision"],
        "calibration_matches_accepted_phase6": True,
        "original_compose_files_preserved": True,
        "model_and_corpus_mounts_preserved": True,
        "private_review_store_configured": state.get("store_validated", False),
        "startup_command_preserved": state.get("startup_command_pinned", False),
        "database_migrations_performed": False,
        "evidence_or_reviews_seeded": False,
        "production_release_certified": False,
    } | extra
    write_json(Path(state["directory"]) / "PUBLIC_RESULT.json", result)
    print("STATUS=" + status, flush=True)
    print("RELEASE_COMMIT=" + state["commit"])
    print("MATCHED_APPLICATION_SOURCES=317")
    print("DATABASE_REVISION=" + state["database_revision"])
    print("CALIBRATION_MATCH=true")
    print("PRIVATE_REVIEW_STORE_VALID=" + str(state.get("store_validated", False)).lower())
    if extra.get("candidate_checks"):
        print("MODEL_HTTP_200=" + str(extra["candidate_checks"].get(
            "trusted_operator_model_http_200", False)).lower())
        print("ARTICLE_HTTP_200=" + str(extra["candidate_checks"].get("article_http_200", False)).lower())
    replaced = extra.get("production_api_replaced")
    print("PRODUCTION_API_REPLACED=" + ("unknown" if replaced is None else str(replaced).lower()))
    print("PUBLIC_RESULT=" + str(Path(state["directory"]) / "PUBLIC_RESULT.json"), flush=True)
    return result


def unchanged(state):
    for name, digest in state["original_file_hashes"].items():
        p = Path(name)
        require(p.is_file() and not p.is_symlink() and fingerprint(p.read_bytes()) == digest,
                "ORIGINAL_SERVER_FILE_CHANGED")
    require(fingerprint((Path(state["repo"]) / CALIBRATION).read_bytes()) == CAL_SHA,
            "CALIBRATION_CHANGED")


def stage(repo, commit):
    require(os.name == "posix" and platform.machine() == "x86_64",
            "EXISTING_X86_64_AWS_HOST_REQUIRED")
    repo = repo.resolve()
    m = load_commit_manifest(repo, commit)
    api = inspect_container(API)
    require(api["Config"].get("Image") == "verifier-api:phase13f-01777cf"
            and api.get("State", {}).get("Health", {}).get("Status") == "healthy",
            "HEALTHY_OBSERVED_BASE_API_REQUIRED")
    env = environment(api["Config"].get("Env"))
    require(env.get("APP_ENV") == "production"
            and env.get("ARTICLE_VERIFICATION_ENABLED", "").strip().lower() != "true"
            and not env.get("ORIGIN_REVIEW_STORE", "").strip()
            and len(env.get("INTERNAL_API_TOKEN", "").strip()) >= 32,
            "OBSERVED_BASE_API_FLAGS_CHANGED")
    require(fingerprint((repo / CALIBRATION).read_bytes()) == CAL_SHA,
            "CALIBRATION_DIFFERS_FROM_ACCEPTED_TEST")
    revision = migration()
    image = inspect_image(api["Image"])
    require(image["Id"] == inspect_image(api["Config"]["Image"])["Id"],
            "BASE_API_IMAGE_TAG_MOVED")
    prefix, model, originals, project = compose_base(
        repo, api, image, pin_running_process=True)
    require(shutil.disk_usage(repo).free >= 2 * 1024 ** 3, "LESS_THAN_2_GIB_DISK_FREE")
    networks = list(api["NetworkSettings"]["Networks"])
    require(len(networks) == 1, "MULTIPLE_API_NETWORKS_REQUIRE_REVIEW")
    operation = uuid4().hex
    directory = private_home() / (commit[:12] + "-" + operation[:8])
    directory.mkdir(mode=0o700)
    source = directory / "source"
    source.mkdir(mode=0o700)
    state = {
        "version": VERSION, "phase": "STAGING", "operation": operation, "commit": commit,
        "repo": str(repo), "directory": str(directory), "project": project,
        "compose_prefix": prefix, "database_revision": revision,
        "compose_working_directory": prefix[prefix.index("--project-directory") + 1],
        "original_container_id": api["Id"], "original_image_id": api["Image"],
        "expected_process_sha256": process_fingerprint(api["Config"]),
        "original_file_hashes": {str(Path(p)): fingerprint(Path(p).read_bytes()) for p in originals},
        "candidate": "verifier-review-stage-" + operation[:12],
        "image": "verifier-api:reviewed-" + commit[:12] + "-" + operation[:8],
        "store": str(directory.parent.parent / "origin-review-store"),
    }
    write_json(directory / "state.json", state, exclusive=True)
    write_json(directory / "PRIVATE_CONTAINER_SNAPSHOT.json", api, exclusive=True)
    print("AWS_PREFLIGHT_PASSED", flush=True)
    try:
        # Pin the measured working process instead of changing it to an on-disk
        # default. Full environment/mount/user checks already passed above.
        # Re-render and compare the complete effective process before any build.
        startup_path = directory / "PRIVATE_STARTUP.override.json"
        write_json(startup_path, escape_compose(startup_override(api)), exclusive=True)
        prefix = [*prefix, "-f", str(startup_path)]
        model = compose_config(prefix)
        validate_base(model, api, image)
        state["compose_prefix"] = prefix
        state["startup_command_pinned"] = True
        print("STARTUP_COMMAND_PRESERVED_FROM_RUNNING_API", flush=True)
        extract_build(repo, commit, source, m)
        state["base_runtime_source_files_matched"] = validate_running_sources(repo, API)
        held_tag = "verifier-api:rollback-" + operation[:16]
        docker("image", "tag", api["Image"], held_tag)
        state["rollback_tag"] = held_tag
        # Keep the proven runtime and locked dependencies; replace code only.
        # This build has no dependency-install step and no network-enabled RUN.
        (source / "Dockerfile.reviewed-release").write_text(
            "FROM " + held_tag + "\n"
            "USER root\n"
            "RUN rm -rf /app/apps/api /app/ml\n"
            "COPY --chown=10001:10001 apps/api /app/apps/api\n"
            "COPY --chown=10001:10001 ml /app/ml\n"
            "USER verifier\n", encoding="utf-8")
        long_run([*DOCKER, "build", "--platform", "linux/amd64", "--pull=false",
                  "--network=none", "-f", "Dockerfile.reviewed-release",
                  "-t", state["image"], "."],
                 directory / "PRIVATE_BUILD.log", "API_BUILD", cwd=source)
        built = inspect_image(state["image"])
        require(built["Config"].get("User") == "verifier", "API_MUST_REMAIN_NONROOT")
        state["image_id"] = built["Id"]
        store = Path(state["store"])
        ensure_store(state["image"], store)
        state["store_validated"] = True
        override = {"services": {"api": {
            "image": state["image"],
            "environment": {"ARTICLE_VERIFICATION_ENABLED": "true",
                            "ORIGIN_REVIEW_STORE": STORE_TARGET},
            "volumes": [{"type": "bind", "source": str(store), "target": STORE_TARGET,
                         "read_only": True, "bind": {"create_host_path": False}}]
        }}}
        override_path = directory / "reviewed-api.override.json"
        write_json(override_path, escape_compose(override), exclusive=True)
        state["promotion_prefix"] = [*prefix, "-f", str(override_path)]
        changed = compose_config(state["promotion_prefix"])
        validate_override(model, changed, state["image"], store)
        rollback_model = copy.deepcopy(model)
        rollback_model["services"]["api"]["image"] = held_tag
        rollback_path = directory / "PRIVATE_ROLLBACK_CONFIG.json"
        write_json(rollback_path, escape_compose(rollback_model), exclusive=True)
        state["rollback_prefix"] = [*DOCKER, "compose", "--project-name", project,
            "--project-directory", state["compose_working_directory"], "-f", str(rollback_path)]
        require(compose_config(state["rollback_prefix"]) == rollback_model,
                "ROLLBACK_CONFIG_ROUNDTRIP_DIFFERS")
        state["rollback_tag"] = held_tag
        require(inspect_image(held_tag)["Id"] == state["original_image_id"],
                "ROLLBACK_IMAGE_NOT_PRESERVED")
        memory_text = Path("/proc/meminfo").read_text()
        available = re.search(r"^MemAvailable:\s+(\d+)\s+kB$", memory_text, re.M)
        require(available is not None and int(available[1]) * 1024 >= 3 * 1024 ** 3,
                "LESS_THAN_3_GIB_MEMORY_AVAILABLE_FOR_MODEL_STAGE")
        memory_limit = str(min(4 * 1024 ** 3, int(available[1]) * 1024 - 1024 ** 3))
        candidate_env = env | {"ARTICLE_VERIFICATION_ENABLED": "true",
                               "ORIGIN_REVIEW_STORE": STORE_TARGET}
        env_path = directory / "PRIVATE_CANDIDATE.env"
        with env_path.open("xb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write("".join(k + "=" + v + "\n" for k, v in candidate_env.items()).encode())
        mounts = actual_mounts(api) | {
            STORE_TARGET: {"type": "bind", "source": str(store), "read_only": True}}
        state["expected_promoted_mounts"] = mounts
        state["expected_promoted_environment_sha256"] = fingerprint(
            json.dumps(candidate_env, sort_keys=True).encode())
        cfg = api["Config"]
        entry = vector(cfg.get("Entrypoint"))
        command = vector(cfg.get("Cmd"))
        require(entry or command, "API_COMMAND_UNSUPPORTED")
        args = ["create", "--name", state["candidate"], "--network", networks[0],
                "--label", "verifier.phase7.operation=" + operation,
                "--memory", memory_limit, "--memory-swap", memory_limit,
                "--env-file", str(env_path), "--user", cfg.get("User") or "verifier",
                "--workdir", cfg.get("WorkingDir") or "/app",
                *mount_args(mounts), "--entrypoint", entry[0] if entry else "",
                state["image"], *entry[1:], *command]
        docker(*args)
        candidate = inspect_container(state["candidate"])
        state["candidate_id"] = candidate["Id"]
        require(environment(candidate["Config"].get("Env")) == candidate_env
                and actual_mounts(candidate) == mounts
                and process_fingerprint(candidate["Config"]) == state["expected_process_sha256"]
                and not candidate["HostConfig"].get("PortBindings"),
                "CANDIDATE_CONFIGURATION_DIFFERS")
        docker("start", state["candidate"])
        checks = wait_ready(state["candidate"])
        checks |= store_probe(state["candidate"])
        print("RUNNING_TRUSTED_OPERATOR_MODEL_AND_ARTICLE_SMOKE", flush=True)
        checks |= model_smoke(state["candidate"])
        state["candidate_checks"] = checks
        unchanged(state)
        require(inspect_container(API)["Id"] == state["original_container_id"],
                "LIVE_API_CHANGED_DURING_STAGING")
        state["phase"] = "STAGED"
        state["private_plan_hashes"] = {
            str(p): fingerprint(p.read_bytes()) for p in (startup_path, override_path, rollback_path)}
        write_json(directory / "state.json", state)
        public_result(state, "STAGED_API_READY", candidate_checks=checks,
                      production_api_replaced=False)
        print("STATE_FILE=" + str(directory / "state.json"))
        print("PROMOTE_COMMAND=" + operation_command("promote", directory / "state.json"))
        print("ROLLBACK_COMMAND=" + operation_command("rollback", directory / "state.json"))
        return state
    except BaseException:
        state["phase"] = "STAGING_FAILED"
        write_json(directory / "state.json", state)
        if "candidate_id" in state:
            try:
                remove_candidate(state)
            except ReleaseError:
                pass
        public_result(state, "STAGING_STOPPED", production_api_replaced=False)
        raise


def model_smoke(name):
    # This is an authorized internal operator check, not a Google OAuth test.
    # The service token is read inside the container and never printed.
    code = (
        "import json,os,urllib.request\n"
        "headers={'Content-Type':'application/json','X-Service-Token':os.environ['INTERNAL_API_TOKEN'],"
        "'X-Verified-User':'operator:phase7_release_smoke'}\n"
        "def request(path,body):\n"
        " q=urllib.request.Request('http://127.0.0.1:8000'+path,data=json.dumps(body).encode(),headers=headers,method='POST')\n"
        " with urllib.request.urlopen(q,timeout=180) as r:\n"
        "  assert r.status==200\n"
        "  return json.load(r)\n"
        "v=request('/api/v1/verify',{'claim':'The Eiffel Tower is in Paris.','top_k':5})\n"
        "assert v.get('assessed_count',0)>0 and v.get('retrieved_count',0)>0\n"
        "assert v.get('confidence_threshold')==0.90\n"
        "a=request('/api/v1/article/verify',{'kind':'pasted','text':"
        "'Chandrayaan-3 landed on the Moon.\\nThis background paragraph explains the scope of this local check without adding independent evidence.'})\n"
        "assert a.get('candidate_count')==1 and a.get('assessed_count')==1 and len(a.get('claims',[]))==1\n"
        "assert a.get('failed_count')==0 and a.get('overall_article_truth_verdict') is None\n"
        "assert a.get('overall_article_truth_probability') is None\n"
        "assert a.get('independent_corroboration_established') is False\n"
        "assert all('external_trusted_origin_review' in c and 'external_reviewed_corroboration' in c for c in a['claims'])\n"
        "print(json.dumps({'trusted_operator_model_http_200':True,'model_assessed_evidence':True,"
        "'threshold_unchanged':True,'article_http_200':True,'article_assessed_one_claim':True,"
        "'article_truth_verdict_unavailable':True,'google_oauth_test_performed':False}))\n"
    )
    result = json.loads(docker("exec", name, "python", "-c", code, timeout=400))
    require(result.get("trusted_operator_model_http_200") is True
            and result.get("article_http_200") is True
            and result.get("threshold_unchanged") is True, "MODEL_OR_ARTICLE_SMOKE_FAILED")
    return result


def operation_command(command, state):
    return ("python3 " + shlex.quote(str(Path(__file__).resolve())) + " " + command
            + " --state " + shlex.quote(str(state)) + "; #")


def load_state(path):
    path = path.absolute()
    require(not path.is_symlink() and path.resolve().is_relative_to(private_home())
            and path.name == "state.json", "PRIVATE_RELEASE_STATE_REQUIRED")
    require(path.is_file() and path.stat().st_uid == os.getuid()
            and path.stat().st_mode & 0o077 == 0, "PRIVATE_STATE_PERMISSIONS_DIFFER")
    state = json.loads(path.read_bytes())
    require(state.get("version") == VERSION and OID.fullmatch(state.get("commit", ""))
            and re.fullmatch(r"[a-f0-9]{32}", state.get("operation", ""))
            and Path(state["directory"]).resolve() == path.parent.resolve(),
            "PRIVATE_RELEASE_STATE_INVALID")
    for key in ("promotion_prefix", "rollback_prefix"):
        require(state.get(key, [])[:3] == [*DOCKER, "compose"],
                "PRIVATE_COMPOSE_PLAN_INVALID")
    return state


def check_plan(state):
    unchanged(state)
    for name, digest in state["private_plan_hashes"].items():
        p = Path(name)
        require(p.is_file() and not p.is_symlink() and fingerprint(p.read_bytes()) == digest,
                "PRIVATE_RELEASE_PLAN_CHANGED")
    require(inspect_image(state["image"])["Id"] == state["image_id"],
            "STAGED_IMAGE_TAG_MOVED")
    require(inspect_image(state["rollback_tag"])["Id"] == state["original_image_id"],
            "ROLLBACK_IMAGE_TAG_MOVED")
    require(migration() == state["database_revision"], "DATABASE_CHANGED")


def rollback(state, *, automatic=False):
    require(state["phase"] in {"PROMOTING", "PROMOTED", "PROMOTION_FAILED", "ROLLBACK_FAILED"},
            "RELEASE_HAS_NOT_REPLACED_PRODUCTION")
    require(inspect_image(state["rollback_tag"])["Id"] == state["original_image_id"],
            "ROLLBACK_IMAGE_TAG_MOVED")
    target = Path(state["directory"])
    try:
        long_run([*state["rollback_prefix"], "up", "-d", "--no-deps", "--no-build",
                  "--pull", "never", "--timeout", "300", "api"],
                 target / ("PRIVATE_ROLLBACK_" + uuid4().hex[:8] + ".log"),
                 "API_ROLLBACK", timeout=600)
        restored = inspect_container(API)
        require(restored["Image"] == state["original_image_id"],
                "ROLLBACK_DID_NOT_RESTORE_ORIGINAL_IMAGE")
        require(process_fingerprint(restored["Config"]) == state["expected_process_sha256"],
                "ROLLBACK_STARTUP_PROCESS_DIFFERS")
        wait_ready(API)
        state["phase"] = "ROLLED_BACK"
        write_json(target / "state.json", state)
        return public_result(state, "ORIGINAL_API_RESTORED", automatic_rollback=automatic,
                             production_api_replaced=False)
    except BaseException:
        state["phase"] = "ROLLBACK_FAILED"
        write_json(target / "state.json", state)
        public_result(state, "ROLLBACK_NEEDS_ATTENTION", automatic_rollback=automatic,
                      production_api_replaced=None)
        raise


def promote(state):
    if state["phase"] == "PROMOTED":
        require(inspect_container(API)["Image"] == state["image_id"],
                "PROMOTED_API_CHANGED")
        return public_result(state, "AWS_API_RELEASED", production_api_replaced=True,
                             vercel_google_oauth_smoke_still_required=True)
    require(state["phase"] == "STAGED" and state.get("store_validated") is True
            and state.get("candidate_checks", {}).get("trusted_operator_model_http_200") is True
            and state.get("expected_process_sha256"),
            "SUCCESSFUL_MODEL_AND_ARTICLE_STAGE_REQUIRED")
    check_plan(state)
    require(inspect_container(API)["Id"] == state["original_container_id"],
            "LIVE_API_CHANGED_SINCE_STAGING")
    require(inspect_container(state["candidate"])["Id"] == state["candidate_id"],
            "CANDIDATE_CHANGED_SINCE_STAGING")
    wait_ready(state["candidate"], seconds=30)
    remove_candidate(state)
    state["phase"] = "PROMOTING"
    target = Path(state["directory"])
    write_json(target / "state.json", state)
    try:
        long_run([*state["promotion_prefix"], "up", "-d", "--no-deps", "--no-build",
                  "--pull", "never", "--timeout", "300", "api"],
                 target / "PRIVATE_PROMOTION.log", "API_REPLACEMENT", timeout=600)
        active = inspect_container(API)
        require(active["Image"] == state["image_id"], "NEW_API_IMAGE_NOT_ACTIVE")
        flags = environment(active["Config"].get("Env"))
        require(flags.get("ARTICLE_VERIFICATION_ENABLED") == "true"
                and flags.get("ORIGIN_REVIEW_STORE") == STORE_TARGET,
                "NEW_API_FLAGS_NOT_ACTIVE")
        require(actual_mounts(active) == state["expected_promoted_mounts"]
                and fingerprint(json.dumps(flags, sort_keys=True).encode())
                == state["expected_promoted_environment_sha256"],
                "NEW_API_ENVIRONMENT_OR_MOUNTS_DIFFER")
        require(process_fingerprint(active["Config"]) == state["expected_process_sha256"],
                "NEW_API_STARTUP_PROCESS_DIFFERS")
        checks = wait_ready(API)
        checks |= store_probe(API)
        checks |= model_smoke(API)
        unchanged(state)
        state["phase"] = "PROMOTED"
        write_json(target / "state.json", state)
        return public_result(state, "AWS_API_RELEASED", production_api_replaced=True,
                             candidate_checks=checks,
                             vercel_google_oauth_smoke_still_required=True)
    except BaseException:
        state["phase"] = "PROMOTION_FAILED"
        write_json(target / "state.json", state)
        rollback(state, automatic=True)
        raise ReleaseError("NEW_API_CHECK_FAILED_ORIGINAL_API_RESTORED") from None


def review(state, action, *, draft=None, key_id=None, record_id=None,
           confirm_distinct=False, valid_days=7):
    require(state["phase"] in {"STAGED", "PROMOTED"}, "ACTIVE_RELEASE_STATE_REQUIRED")
    require(inspect_image(state["image"])["Id"] == state["image_id"],
            "REVIEW_TOOL_IMAGE_CHANGED")
    store = state["store"]
    prefix = ["run", "--rm", "-i", "--network", "none", "--read-only",
              "--user", "10001:10001", "--entrypoint", "python",
              "--mount", f"type=bind,src={store},dst=/origin-review"]
    data = {"action": action, "key_id": key_id, "record_id": record_id,
            "confirm_distinct": confirm_distinct, "valid_days": valid_days}
    if action == "sign":
        require(draft is not None and not draft.is_symlink() and draft.is_file()
                and draft.stat().st_size <= 262144, "PUBLIC_REVIEW_DRAFT_REQUIRED")
        data["draft"] = json.loads(draft.read_text(encoding="utf-8-sig"))
    code = (
        "import json,sys; from pathlib import Path\n"
        "from apps.api.services.trusted_reporting_review import registry,sign_review,revoke_review\n"
        "d=json.load(sys.stdin); p=Path('/origin-review')\n"
        "if d['action']=='reviewers':\n"
        " r=registry(p); result={'reviewers':[{'key_id':k,'label':v['label'],'active':v['active']} for k,v in r['reviewers'].items()]}\n"
        "elif d['action']=='sign':\n"
        " result=sign_review(p,d['draft'],d['key_id'],confirm_distinct=d['confirm_distinct'],valid_days=d['valid_days'])\n"
        "else:\n"
        " revoke_review(p,record_id=d['record_id'],key_id=d['key_id']); result={'status':'REVIEW_REVOKED'}\n"
        "print(json.dumps(result))\n"
    )
    result = json.loads(docker(*prefix, state["image"], "-c", code,
                               data=json.dumps(data).encode()))
    print(json.dumps(result, indent=2))
    return result


def cancel(state):
    require(state["phase"] == "STAGED", "ONLY_AN_UNPROMOTED_STAGE_CAN_BE_CANCELLED")
    remove_candidate(state)
    state["phase"] = "CANCELLED"
    write_json(Path(state["directory"]) / "state.json", state)
    return public_result(state, "STAGE_CANCELLED", production_api_replaced=False)


def release(repo, commit):
    state = stage(repo, commit)
    return promote(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--publish", action="store_true")
    for command in ("stage", "release"):
        p = commands.add_parser(command)
        p.add_argument("--repo", type=Path, required=True)
        p.add_argument("--commit", required=True)
    for command in ("promote", "rollback", "cancel", "review"):
        p = commands.add_parser(command)
        p.add_argument("--state", type=Path, required=True)
        if command == "review":
            p.add_argument("action", choices=("reviewers", "sign", "revoke"))
            p.add_argument("--draft", type=Path)
            p.add_argument("--key-id")
            p.add_argument("--record-id")
            p.add_argument("--confirm-distinct-reporting-review", action="store_true")
            p.add_argument("--valid-days", type=int, default=7)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.repo, Path(__file__).resolve().parent, publish=args.publish)
    elif args.command == "stage":
        stage(args.repo, args.commit)
    elif args.command == "release":
        release(args.repo, args.commit)
    else:
        require(os.name == "posix", "AWS_UBUNTU_TERMINAL_REQUIRED")
        state = load_state(args.state)
        if args.command == "promote":
            promote(state)
        elif args.command == "rollback":
            rollback(state)
        elif args.command == "cancel":
            cancel(state)
        else:
            if args.action == "revoke":
                require(bool(args.key_id) != bool(args.record_id),
                        "EXACTLY_ONE_REVOCATION_TARGET_REQUIRED")
            review(state, args.action, draft=args.draft, key_id=args.key_id,
                   record_id=args.record_id, valid_days=args.valid_days,
                   confirm_distinct=args.confirm_distinct_reporting_review)


def remote_allowed(value):
    return re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)"
        r"Aleem547/explainable-news-verifier(?:\.git)?", value, re.I) is not None


def stage_command(repo, branch, commit, *, action="stage"):
    require(action in {"stage", "release"}, "INVALID_AWS_RELEASE_ACTION")
    bootstrap = f"$HOME/phase7-release-{commit[:12]}.py"
    return (
        f"cd {shlex.quote(repo.as_posix())} && git fetch origin {shlex.quote(branch)}"
        f" && git show {commit}:{GIT_FOLDER}/release_tool.py > \"{bootstrap}\""
        f" && python3 \"{bootstrap}\" {action} --repo . --commit {commit}; #"
    )


def prepare(repo, folder, *, publish=False, allow_local_remote=False):
    repo, folder = repo.resolve(), folder.resolve()
    m = package_manifest(folder)
    require(Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
            == repo, "ORIGINAL_GIT_CHECKOUT_REQUIRED")
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    require(head == m.get("base_head", BASE_HEAD), "BASE_COMMIT_CHANGED")
    branch_before = git(repo, "symbolic-ref", "--quiet", "HEAD")
    require(branch_before.strip() not in (b"refs/heads/main", b"refs/heads/master"),
            "DEVELOPMENT_BRANCH_REQUIRED")
    require(not git(repo, "ls-files", "-u"), "UNRESOLVED_GIT_CONFLICTS")
    tracked = [p.decode() for p in git(repo, "ls-files", "-z").split(b"\0") if p]
    require(not any(SENSITIVE.search(p) and not p.endswith(
        (".example", ".sample", ".template")) for p in tracked), "TRACKED_PRIVATE_FILE")
    source = validated_sources(repo, m)
    for name in ("pyproject.toml", "uv.lock", "infra/docker/api/Dockerfile"):
        require(fingerprint(normalize(git(repo, "show", head + ":" + name)))
                == m["source_checksums"][name], "BUILD_BASE_CHANGED:" + name)
    index_path = Path(git(repo, "rev-parse", "--git-path", "index").decode().strip())
    if not index_path.is_absolute():
        index_path = repo / index_path
    index_before = index_path.read_bytes() if index_path.exists() else None
    payload = {f"{GIT_FOLDER}/{name}": read(folder, name)
               for name in ("release_tool.py", "release_manifest.json", "README.md")}
    for name, raw in payload.items():
        # Keep a prior, unrelated tool at the same path out of this release.
        p = checked(repo, name)
        require(not p.exists() or p.is_file() and normalize(p.read_bytes()) == normalize(raw),
                "EXISTING_RELEASE_TOOL_CONFLICT")
    with tempfile.TemporaryDirectory(prefix="verifier-release-index-") as temp:
        isolated = Path(temp) / "index"
        git(repo, "read-tree", head, index=isolated)
        entries = []
        for name, raw in (source | payload).items():
            oid = git(repo, "hash-object", "-w", "--stdin", data=raw).decode().strip()
            require(OID.fullmatch(oid), "INVALID_GIT_OBJECT")
            entries.append(f"100644 {oid}\t{name}\0".encode())
        git(repo, "update-index", "-z", "--index-info", data=b"".join(entries), index=isolated)
        tree = git(repo, "write-tree", index=isolated).decode().strip()
        validated_sources(repo, m)
        require(git(repo, "rev-parse", "HEAD").decode().strip() == head
                and git(repo, "symbolic-ref", "--quiet", "HEAD") == branch_before
                and (index_path.read_bytes() if index_path.exists() else None) == index_before,
                "DEVELOPER_CHECKOUT_CHANGED_DURING_PREPARATION")
        commit = git(repo, "commit-tree", tree, "-p", head, "-F", "-", data=(
            "feat: release authenticated reporting-origin review\n\n"
            "Accepted Phase 6 application sources; guarded AWS release and rollback.\n"
        ).encode()).decode().strip()
    require(OID.fullmatch(commit), "INVALID_RELEASE_COMMIT")
    branch = "release/phase7-reviewed-" + commit[:12]
    try:
        prior = git(repo, "rev-parse", "--verify", "refs/heads/" + branch).decode().strip()
    except ReleaseError:
        prior = None
    require(prior is None or prior == commit, "RELEASE_BRANCH_ALREADY_EXISTS")
    if prior is None:
        git(repo, "update-ref", "refs/heads/" + branch, commit, "0" * len(commit))
    result = {"status": "RELEASE_BRANCH_PREPARED", "branch": branch, "commit": commit,
              "application_files_matched": 317, "working_branch_preserved": True,
              "git_index_preserved": True, "published": False,
              "production_deployment_performed": False}
    result["aws_stage_command"] = stage_command(
        Path("/home/ubuntu/explainable-news-verifier"), branch, commit)
    result["aws_release_command"] = stage_command(
        Path("/home/ubuntu/explainable-news-verifier"), branch, commit, action="release")
    output = checked(repo, "artifacts/phase7_release/prepared_" + commit[:12] + ".json")
    write_json(output, result)
    if publish:
        remote = git(repo, "remote", "get-url", "origin").decode().strip()
        require(remote_allowed(remote) or allow_local_remote, "EXPECTED_GITHUB_ORIGIN_REQUIRED")
        # Normal, non-force push of exactly one new branch. No main/master update.
        git(repo, "push", "origin", "refs/heads/" + branch + ":refs/heads/" + branch,
            timeout=180)
        result["published"] = True
        result["status"] = "RELEASE_BRANCH_PUBLISHED"
    require(git(repo, "symbolic-ref", "--quiet", "HEAD") == branch_before
            and (index_path.read_bytes() if index_path.exists() else None) == index_before,
            "DEVELOPER_CHECKOUT_CHANGED_DURING_PREPARATION")
    write_json(output, result)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in {"aws_stage_command", "aws_release_command"}}, indent=2))
    print("\nAWS_RELEASE_COMMAND (stages, tests, then releases the API; include final ; #):\n"
          + result["aws_release_command"])
    return result


if __name__ == "__main__":
    try:
        main()
    except (ReleaseError, OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if type(error) is ReleaseError else "RELEASE_INPUT_UNAVAILABLE"
        print(json.dumps({"status": "STOPPED", "code": code,
                          "private_values_exported": False}))
        raise SystemExit(1)
