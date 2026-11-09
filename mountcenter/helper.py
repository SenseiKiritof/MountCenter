#!/usr/bin/env python3
"""Privileged helper for MountCenter.

Run as root, normally through pkexec from the GUI:
    pkexec /usr/libexec/mountcenter/helper.py apply --uuid ... --mount-point ...
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mountcenter.core import (  # noqa: E402
    FSTAB_DEFAULT,
    POLKIT_ACTION,
    TRUST_RULE,
    FstabEntry,
    build_entry,
    find_by_mount_point,
    find_by_uuid,
    parse_fstab,
    unescape_field,
)

SYSTEMD_RUNTIME = "/run/systemd/system"


class HelperError(Exception):
    """User-facing error; reported as JSON and exit code 1."""


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _backup(path: str) -> str:
    backup = f"{path}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(path, backup)
    return backup


def _write_atomic(path: str, text: str) -> None:
    target = Path(path)
    mode = target.stat().st_mode & 0o7777 if target.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        if target.exists() and os.geteuid() == 0:
            stat = target.stat()
            os.chown(tmp, stat.st_uid, stat.st_gid)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _lock(fstab_path: str):
    lock_path = (
        "/run/lock/mountcenter.lock"
        if fstab_path == FSTAB_DEFAULT
        else f"{fstab_path}.lock"
    )
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _require_root(fstab_path: str) -> None:
    if fstab_path == FSTAB_DEFAULT and os.geteuid() != 0:
        raise HelperError("Questa operazione richiede i privilegi di root.")


def _check_device(uuid: str, fstype: str) -> None:
    device = f"/dev/disk/by-uuid/{uuid}"
    if not os.path.exists(device):
        raise HelperError(f"Device con UUID {uuid} non trovato.")
    result = subprocess.run(
        ["blkid", "-s", "TYPE", "-o", "value", device],
        capture_output=True,
        text=True,
        check=False,
    )
    real = result.stdout.strip()
    if not real:
        raise HelperError(f"Impossibile determinare il filesystem di {device}.")
    if real.lower() != fstype.lower():
        raise HelperError(
            f"Il device {device} è {real}, non {fstype}. Aggiorna e riprova."
        )


def _use_systemd(fstab_path: str) -> bool:
    return fstab_path == FSTAB_DEFAULT and os.path.isdir(SYSTEMD_RUNTIME)


def _mount_unit(mount_point: str) -> str:
    result = subprocess.run(
        ["systemd-escape", "--path", "--suffix=mount", mount_point],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _verify_unit(mount_point: str) -> str:
    unit = _mount_unit(mount_point)
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    state = subprocess.run(
        ["systemctl", "show", "-p", "LoadState", "--value", unit],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if state != "loaded":
        raise HelperError(
            f"Riga fstab non valida: unità {unit} non generata (LoadState={state})."
        )
    return unit


def apply(
    entry: FstabEntry,
    *,
    fstab_path: str = FSTAB_DEFAULT,
    verify_device: bool = True,
) -> dict:
    """Append a validated entry to fstab, with backup and systemd verification."""
    _require_root(fstab_path)
    with _lock(fstab_path):
        text = _read(fstab_path)
        entries = parse_fstab(text)
        if find_by_uuid(entries, entry.uuid or ""):
            raise HelperError(f"L'UUID {entry.uuid} è già presente in {fstab_path}.")
        if find_by_mount_point(entries, entry.mount_point):
            raise HelperError(
                f"Il punto di montaggio {entry.mount_point} è già presente in {fstab_path}."
            )
        if verify_device:
            _check_device(entry.uuid or "", entry.fstype)

        backup = _backup(fstab_path)
        new_text = text if not text or text.endswith("\n") else text + "\n"
        new_text += entry.to_line() + "\n"
        _write_atomic(fstab_path, new_text)

    result = {"ok": True, "line": entry.to_line(), "backup": backup}
    if _use_systemd(fstab_path):
        try:
            result["unit"] = _verify_unit(entry.mount_point)
        except (HelperError, subprocess.CalledProcessError, FileNotFoundError) as error:
            _write_atomic(fstab_path, text)
            with contextlib.suppress(Exception):
                os.unlink(backup)
            raise HelperError(f"Configurazione annullata: {error}") from error
    return result


def _remove_uuid(text: str, uuid: str) -> tuple[str, int]:
    needle = f"uuid={uuid}".lower()
    kept: list[str] = []
    removed = 0
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            fields = stripped.split()
            if len(fields) >= 4:
                spec = unescape_field(fields[0]).lower()
                if spec == needle:
                    removed += 1
                    continue
        kept.append(raw)
    if removed and kept and not kept[-1].endswith("\n"):
        kept[-1] += "\n"
    return "".join(kept), removed


def remove(*, uuid: str, fstab_path: str = FSTAB_DEFAULT) -> dict:
    _require_root(fstab_path)
    with _lock(fstab_path):
        text = _read(fstab_path)
        new_text, removed = _remove_uuid(text, uuid)
        if not removed:
            raise HelperError(f"UUID {uuid} non trovato in {fstab_path}.")
        backup = _backup(fstab_path)
        _write_atomic(fstab_path, new_text)
    result = {"ok": True, "removed": removed, "backup": backup}
    if _use_systemd(fstab_path):
        subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)
    return result


def status(*, fstab_path: str = FSTAB_DEFAULT) -> dict:
    entries = parse_fstab(_read(fstab_path))
    return {
        "ok": True,
        "fstab": fstab_path,
        "entries": [
            {
                "line": entry.line_no,
                "uuid": entry.uuid,
                "mount_point": entry.mount_point,
                "fstype": entry.fstype,
                "options": entry.options,
                "automount": entry.automount,
            }
            for entry in entries
        ],
    }


# --- Remembered authorization: polkit rule for the calling user -----------------


def trust_user() -> str | None:
    """User who called the helper via pkexec (GUI) or sudo (CLI); None if unknown."""
    uid = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    if uid:
        try:
            return pwd.getpwuid(int(uid)).pw_name
        except (KeyError, ValueError):
            return None
    return None


def current_user() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def trust_users(rule: str = TRUST_RULE) -> list[str]:
    try:
        text = Path(rule).read_text(encoding="utf-8")
    except OSError:
        return []
    match = re.search(r"(\[[^\]]*\])\.indexOf\(subject\.user\)", text)
    return json.loads(match.group(1)) if match else []


def _trust_rule_text(users: list[str]) -> str:
    return (
        "// Generated by `mountcenter-helper trust on`: these users run MountCenter"
        " without re-entering the password.\n"
        f"// Applies only to the action {POLKIT_ACTION} (pkexec mountcenter-helper)"
        " in an active local session.\n"
        "polkit.addRule(function(action, subject) {\n"
        f'    if (action.id == "{POLKIT_ACTION}" && subject.local && subject.active &&\n'
        f"        {json.dumps(users)}.indexOf(subject.user) >= 0)\n"
        "        return polkit.Result.YES;\n"
        "});\n"
    )


def trust_write(users: list[str], rule: str = TRUST_RULE) -> None:
    target = Path(rule)
    if not users:
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(str(target), _trust_rule_text(users))


def trust_set(user: str, enabled: bool, rule: str = TRUST_RULE) -> dict:
    if rule == TRUST_RULE and os.geteuid() != 0:
        raise HelperError("Questa operazione richiede i privilegi di root.")
    users = set(trust_users(rule))
    users = users | {user} if enabled else users - {user}
    users = sorted(users)
    trust_write(users, rule)
    return {"ok": True, "trusted": users, "user": user}


def trust_status(rule: str = TRUST_RULE) -> dict:
    users = trust_users(rule)
    user = trust_user() or current_user()
    return {"ok": True, "trusted": users, "user": user, "active": user in users}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mountcenter-helper")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("apply", help="add a disk to fstab")
    add.add_argument("--uuid", required=True)
    add.add_argument("--mount-point", required=True)
    add.add_argument("--fstype", required=True)
    add.add_argument("--uid", type=int)
    add.add_argument("--gid", type=int)
    add.add_argument("--no-automount", action="store_true")
    add.add_argument("--fstab", default=FSTAB_DEFAULT, help=argparse.SUPPRESS)
    add.add_argument("--skip-device-check", action="store_true", help=argparse.SUPPRESS)

    delete = commands.add_parser("remove", help="remove an entry by UUID")
    delete.add_argument("--uuid", required=True)
    delete.add_argument("--fstab", default=FSTAB_DEFAULT, help=argparse.SUPPRESS)

    show = commands.add_parser("status", help="list configured entries")
    show.add_argument("--fstab", default=FSTAB_DEFAULT, help=argparse.SUPPRESS)

    trust = commands.add_parser("trust", help="remember the polkit authorization")
    trust.add_argument("state", choices=("on", "off", "status"))
    trust.add_argument("--rule", default=TRUST_RULE, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "apply":
            entry = build_entry(
                args.uuid,
                args.mount_point,
                args.fstype,
                uid=args.uid,
                gid=args.gid,
                automount=not args.no_automount,
            )
            result = apply(
                entry,
                fstab_path=args.fstab,
                verify_device=not args.skip_device_check,
            )
        elif args.command == "remove":
            result = remove(uuid=args.uuid, fstab_path=args.fstab)
        elif args.command == "trust":
            if args.state == "status":
                result = trust_status(args.rule)
            else:
                user = trust_user()
                if not user:
                    raise HelperError(
                        "Utente non identificato: esegui tramite pkexec o sudo."
                    )
                result = trust_set(user, args.state == "on", args.rule)
        else:
            result = status(fstab_path=args.fstab)
    except (HelperError, ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
