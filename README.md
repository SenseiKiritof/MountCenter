# MountCenter

Configure systemd automount entries in `/etc/fstab` for internal and external
disks on Fedora, without hand-editing the file.

Two front ends share the same rules:

- `mountcenter` — GTK4/libadwaita application, for normal desktop use.
- `setup-automount.sh` — legacy interactive root script, for headless use.

Both derive the UUID with `blkid`, escape spaces and tabs in the mount point
(`\040`, `\011`), refuse duplicate UUIDs and duplicate mount points, back up
`/etc/fstab`, reload systemd and verify that the generated mount unit exists.
The GUI and the helper can mount a disk at boot or on first access; the legacy
script always writes `x-systemd.automount`.

![MountCenter main window: disks on the left, details and fstab preview on the right](docs/screenshots/main.png)

Selecting a disk that is not configured yet shows an editable mount point, the
mount mode and permission switches, and the exact fstab line before applying:

![Configuring a new automatic mount](docs/screenshots/new-mount.png)

## Install

From a release package:

```bash
sudo dnf install ./mountcenter-*.rpm
mountcenter
```

From the source tree:

```bash
sudo ./install.sh
mountcenter
```

`install.sh` installs under `/usr/local` (override with `PREFIX`, stage with
`DESTDIR`). The GUI never writes to `/etc/fstab` directly: it calls
`mountcenter/helper.py` through `pkexec`, and the helper revalidates everything
as root.

Legacy script:

```bash
sudo ./setup-automount.sh
```

## Using the GUI

1. Pick a partition from the list; mounted and already-configured disks are
   labelled.
2. Edit the mount point (default `/mnt/<label>`).
3. Choose when to mount (**All'avvio** or **Al primo accesso**) and, for
   exfat/vfat/ntfs, user permissions.
4. Check the fstab preview, then press **Applica**.
5. Authenticate with polkit. On success the list refreshes.

Entries already present in `/etc/fstab` are shown read-only, with the mount
mode in their subtitle. A check icon means automount on first access, a disk
icon means mounted at boot. Removal is available through the helper:

```bash
sudo mountcenter/helper.py remove --uuid FE7B-D8D1
```

## Mount modes

- **All'avvio** — no `x-systemd.automount`: systemd mounts the disk at boot
  through `local-fs.target`, together with the other fstab entries. `nofail`
  keeps the boot going when the disk is missing.
- **Al primo accesso** — adds `x-systemd.automount`: nothing is mounted at
  boot; the first opening of the mount point triggers the mount. It stays
  mounted until unmount or reboot (no idle timeout).

Neither mode runs `fsck` on exfat/vfat/ntfs: the helper writes `passno 0`.
Entries created by older versions may still have `passno 2`, so `fsck` runs on
first access and can take minutes on a large exfat volume; the detail page
warns and `0 0` in the fstab line fixes it.

## Compatibility

Tested in containers by [`.github/workflows/compat.yml`](.github/workflows/compat.yml)
(core, helper and GUI startup under Xvfb):

| Distribution | Status |
|---|---|
| Fedora 44 / 45 | tested |
| Debian 13 (trixie) | tested |
| Ubuntu 24.04 LTS | tested |
| Arch Linux | tested |
| openSUSE Tumbleweed | tested |

Requirements: a systemd-based distribution, Python 3.10+, GTK 4,
libadwaita 1.5+, polkit with `pkexec`, and util-linux. Distributions without
systemd are not supported, because `x-systemd.automount` is systemd-specific.
Ubuntu 22.04 and Debian 12 ship libadwaita older than 1.5 and are not
supported.

Dependencies by distribution, when installing from source:

| Distribution | Packages |
|---|---|
| Fedora | `python3-gobject gtk4 libadwaita polkit util-linux` |
| Debian / Ubuntu | `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 polkitd pkexec util-linux` |
| Arch | `python-gobject gtk4 libadwaita polkit util-linux` |
| openSUSE | `python3-gobject gtk4 libadwaita typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 polkit util-linux` |

## Remembered authorization (first launch)

On the first start, when the polkit policy is installed, MountCenter offers to
remember the authorization. Accepting asks for the password once and writes
`/etc/polkit-1/rules.d/50-mountcenter.rules`:

- it applies only to the action `io.github.senseikiritof.MountCenter.manage`,
  i.e. to the MountCenter helper run through `pkexec`;
- only to the user who accepted, and only in an active local session;
- it is not a general `sudo` permission and can be revoked at any time.

Revoke it with:

```bash
sudo mountcenter/helper.py trust off
mountcenter/helper.py trust status
```

Without the rule, every apply asks for the password. In a source-tree run
(no installed policy) the trust prompt is skipped, because the custom polkit
action does not exist yet.

## Architecture

```
mountcenter/core.py    pure logic: fstab parse/render, escaping, validation
mountcenter/helper.py  privileged CLI: apply/remove/status/trust, backup, systemd
mountcenter/app.py     GTK4/libadwaita interface
data/                  desktop entry and polkit policy template
tests/                 unittest suite (stdlib only)
Containerfile.test     Fedora container with GTK, xvfb and a private D-Bus
```

Helper commands:

```bash
mountcenter/helper.py status
sudo mountcenter/helper.py apply --uuid UUID --mount-point "/mnt/Data Disk" --fstype exfat --uid 1000 --gid 1000
sudo mountcenter/helper.py remove --uuid UUID
mountcenter/helper.py trust status
```

All commands print JSON; errors also exit with status 1. `--fstab`,
`--skip-device-check` and `--rule` exist only for tests.

## Build and test

```bash
make test
make rpm            # dist/mountcenter-<version>-*.rpm
make dist           # source tarball from HEAD
```

In the dedicated Fedora container (core, helper and a GUI smoke test under
Xvfb with a private D-Bus):

```bash
podman build -t mountcenter-test -f Containerfile.test .
podman run --rm -v "$PWD":/src:Z -w /src mountcenter-test \
    bash -lc 'dbus-run-session -- xvfb-run -a python3 -m unittest discover -s tests -v'
```

The helper tests run against a temporary fstab file: no test touches the real
`/etc/fstab`. Systemd verification is skipped automatically when the target
is not `/etc/fstab` or PID 1 is not systemd.

Releases are built by [`.github/workflows/release.yml`](.github/workflows/release.yml)
on `v*` tags: tests, RPM in a Fedora container, then one GitHub release with
the package and the source tarball.

## Roadmap

See [docs/interface-plan.md](docs/interface-plan.md). Implemented: core logic,
privileged helper, GUI with first-launch trust, install script, RPM and release
workflow. Pending: removal and automount status in the GUI, dedicated polkit
policy refinements, Debian/Arch packages.
