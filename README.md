# MountCenter

Configure systemd automount entries in `/etc/fstab` for internal and external
disks on Fedora, safely and without hand-editing the file.

Current implementation: `setup-automount.sh`, an interactive root script that

- lists block devices with `lsblk`,
- derives UUID, filesystem and label with `blkid`,
- builds a fstab line with `nofail` and `x-systemd.automount`,
- escapes spaces and tabs in the mount point (`\040`, `\011`),
- refuses duplicate UUIDs and duplicate mount points,
- backs up `/etc/fstab` before writing,
- reloads systemd and verifies the generated mount unit exists.

## Usage

```bash
sudo ./setup-automount.sh
```

## Roadmap

A graphical interface (GTK4 / libadwaita) is planned. See
[docs/interface-plan.md](docs/interface-plan.md).
