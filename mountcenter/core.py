"""Pure logic for MountCenter: fstab parsing/rendering, validation, lsblk."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

FSTAB_DEFAULT = "/etc/fstab"

USER_PERM_FSTYPES = {"exfat", "vfat", "ntfs", "ntfs3"}
EXT_FSTYPES = {"ext2", "ext3", "ext4"}

# Destinazioni di sistema: mai usate come punto di montaggio di un disco dati.
SYSTEM_MOUNTS = {
    "/",
    "/boot",
    "/boot/efi",
    "/home",
    "/etc",
    "/usr",
    "/var",
    "/run",
    "/proc",
    "/sys",
    "/dev",
    "/tmp",
    "/root",
}

_ESCAPES = {"\\": "\\\\", " ": "\\040", "\t": "\\011"}
_UNESCAPES = {value: key for key, value in _ESCAPES.items()}
_UNESCAPE_RE = re.compile(r"\\040|\\011|\\\\")


def escape_field(value: str) -> str:
    """Escape a value for a whitespace-separated fstab field."""
    return "".join(_ESCAPES.get(char, char) for char in value)


def unescape_field(value: str) -> str:
    return _UNESCAPE_RE.sub(lambda match: _UNESCAPES[match.group(0)], value)


def normalize_mount_point(path: str) -> str:
    return path.rstrip("/") or "/"


def validate_mount_point(path: str) -> str:
    """Return the normalized mount point or raise ValueError."""
    if not path or not path.startswith("/"):
        raise ValueError("Il punto di montaggio deve essere un percorso assoluto.")
    if any(char in path for char in ("\x00", "\n", "\r")):
        raise ValueError("Il punto di montaggio contiene caratteri non validi.")
    normalized = os.path.normpath(path)
    if normalized == "/":
        raise ValueError("Non è possibile usare / come punto di montaggio.")
    for system in SYSTEM_MOUNTS:
        if system == "/":
            continue
        if normalized == system or normalized.startswith(system + "/"):
            raise ValueError(f"Il punto di montaggio non può stare sotto {system}.")
    return normalized


@dataclass
class FstabEntry:
    spec: str
    mount_point: str
    fstype: str
    options: str = "defaults"
    dump: int = 0
    passno: int = 0
    line_no: int = 0

    @property
    def uuid(self) -> str | None:
        if self.spec.upper().startswith("UUID="):
            return self.spec[5:]
        return None

    @property
    def automount(self) -> bool:
        return "x-systemd.automount" in self.options.split(",")

    def to_line(self) -> str:
        return (
            f"{escape_field(self.spec)}  {escape_field(self.mount_point)}"
            f"  {self.fstype}  {self.options}  {self.dump}  {self.passno}"
        )


def parse_fstab(text: str) -> list[FstabEntry]:
    """Parse fstab text, skipping comments, blank and malformed lines."""
    entries: list[FstabEntry] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        dump = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        passno = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
        entries.append(
            FstabEntry(
                spec=unescape_field(parts[0]),
                mount_point=unescape_field(parts[1]),
                fstype=parts[2],
                options=parts[3],
                dump=dump,
                passno=passno,
                line_no=line_no,
            )
        )
    return entries


def find_by_uuid(entries: list[FstabEntry], uuid: str) -> list[FstabEntry]:
    needle = uuid.lower()
    return [entry for entry in entries if (entry.uuid or "").lower() == needle]


def find_by_mount_point(entries: list[FstabEntry], mount_point: str) -> list[FstabEntry]:
    normalized = normalize_mount_point(mount_point)
    return [
        entry
        for entry in entries
        if normalize_mount_point(entry.mount_point) == normalized
    ]


def default_options(
    fstype: str,
    *,
    uid: int | None = None,
    gid: int | None = None,
    automount: bool = True,
) -> str:
    options = ["defaults", "nofail"]
    if automount:
        options.append("x-systemd.automount")
    if fstype in USER_PERM_FSTYPES:
        if uid is not None:
            options.append(f"uid={uid}")
        if gid is not None:
            options.append(f"gid={gid}")
    return ",".join(options)


def build_entry(
    uuid: str,
    mount_point: str,
    fstype: str,
    *,
    uid: int | None = None,
    gid: int | None = None,
    automount: bool = True,
) -> FstabEntry:
    """Build a validated fstab entry for a data disk."""
    if not uuid.strip():
        raise ValueError("UUID mancante.")
    if not fstype.strip():
        raise ValueError("Filesystem mancante.")
    return FstabEntry(
        spec=f"UUID={uuid.strip()}",
        mount_point=validate_mount_point(mount_point),
        fstype=fstype.strip(),
        options=default_options(fstype, uid=uid, gid=gid, automount=automount),
        dump=0,
        passno=2 if fstype in EXT_FSTYPES else 0,
    )


@dataclass
class Device:
    name: str
    path: str = ""
    type: str = ""
    fstype: str | None = None
    label: str | None = None
    uuid: str | None = None
    size: str | None = None
    mountpoint: str | None = None
    children: list["Device"] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.label or self.name


def parse_lsblk(data: str | dict) -> list[Device]:
    """Parse `lsblk -J` output into a flat list; disks keep their children."""
    payload = json.loads(data) if isinstance(data, str) else data
    devices: list[Device] = []
    for item in payload.get("blockdevices", []):
        devices.append(_device_from_item(item))
    return devices


def _device_from_item(item: dict) -> Device:
    children = [_device_from_item(child) for child in item.get("children") or []]
    return Device(
        name=item.get("name", ""),
        path=item.get("path") or (f"/dev/{item['name']}" if item.get("name") else ""),
        type=item.get("type") or "",
        fstype=item.get("fstype"),
        label=item.get("label"),
        uuid=item.get("uuid"),
        size=item.get("size"),
        mountpoint=item.get("mountpoint"),
        children=children,
    )


def flatten_devices(devices: list[Device]) -> list[Device]:
    flat: list[Device] = []
    for device in devices:
        flat.append(device)
        flat.extend(flatten_devices(device.children))
    return flat
