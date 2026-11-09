# MountCenter

Configure systemd automount entries in `/etc/fstab` for internal and external
disks on Fedora, without hand-editing the file.

Two front ends share the same rules:

- `mountcenter` — GTK4/libadwaita application, for normal desktop use.
- `setup-automount.sh` — legacy interactive root script, for headless use.

Both derive the UUID with `blkid`, write a line with `nofail` and
`x-systemd.automount`, escape spaces and tabs in the mount point (`\040`,
`\011`), refuse duplicate UUIDs and duplicate mount points, back up
`/etc/fstab`, reload systemd and verify that the generated mount unit exists.

## Install and run

```bash
sudo ./install.sh
mountcenter
```

`install.sh` installs under `/usr/local` (override with `PREFIX` or stage with
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
3. Choose automount and, for exfat/vfat/ntfs, user permissions.
4. Check the fstab preview, then press **Applica**.
5. Authenticate with polkit. On success the list refreshes.

Entries already present in `/etc/fstab` are shown read-only. Removal is
available only through the helper for now:

```bash
sudo python3 mountcenter/helper.py remove --uuid FE7B-D8D1
```

## Architecture

```
mountcenter/core.py    pure logic: fstab parse/render, escaping, validation
mountcenter/helper.py  privileged CLI: apply/remove/status, backup, systemd
mountcenter/app.py     GTK4/libadwaita interface
tests/                 unittest suite (stdlib only)
Containerfile.test     Fedora container with GTK, xvfb and a private D-Bus
```

Helper commands:

```bash
python3 mountcenter/helper.py status
sudo python3 mountcenter/helper.py apply --uuid UUID --mount-point "/mnt/Data Disk" --fstype exfat --uid 1000 --gid 1000
sudo python3 mountcenter/helper.py remove --uuid UUID
```

All commands print JSON; errors also exit with status 1. `--fstab` and
`--skip-device-check` exist only for tests.

## Tests

Locally:

```bash
python3 -m unittest discover -s tests -v
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

## Roadmap

See [docs/interface-plan.md](docs/interface-plan.md). Implemented: core logic,
privileged helper, minimal GTK UI, install script. Pending: removal and
automount status in the GUI, polkit policy, RPM packaging.
