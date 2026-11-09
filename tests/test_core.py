import unittest

from mountcenter.core import (
    build_entry,
    default_options,
    escape_field,
    find_by_mount_point,
    find_by_uuid,
    flatten_devices,
    normalize_mount_point,
    parse_fstab,
    parse_lsblk,
    unescape_field,
    validate_mount_point,
)


class EscapeTest(unittest.TestCase):
    def test_space_is_escaped(self):
        self.assertEqual(escape_field("/mnt/Games 2TB"), "/mnt/Games\\0402TB")

    def test_tab_is_escaped(self):
        self.assertEqual(escape_field("/mnt/a\tb"), "/mnt/a\\011b")

    def test_backslash_is_escaped_first(self):
        self.assertEqual(escape_field("/mnt/a\\b"), "/mnt/a\\\\b")

    def test_roundtrip(self):
        for value in ("/mnt/Games 2TB", "/mnt/a\tb", "/mnt/a\\b", "/mnt/plain"):
            self.assertEqual(unescape_field(escape_field(value)), value)


class FstabTest(unittest.TestCase):
    def test_parse_skips_comments_blank_and_malformed(self):
        text = (
            "# commento\n"
            "\n"
            "UUID=FE7B-D8D1  /mnt/Games\\0402TB  exfat  defaults,nofail  0  0\n"
            "riga rotta\n"
            "UUID=AAAA  /boot  ext4  defaults  1  2\n"
        )
        entries = parse_fstab(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].mount_point, "/mnt/Games 2TB")
        self.assertEqual(entries[0].fstype, "exfat")
        self.assertEqual(entries[0].line_no, 3)
        self.assertEqual(entries[1].passno, 2)

    def test_uuid_lookup_is_case_insensitive(self):
        entries = parse_fstab("UUID=FE7B-D8D1  /mnt/x  exfat  defaults  0  0\n")
        self.assertEqual(len(find_by_uuid(entries, "fe7b-d8d1")), 1)
        self.assertEqual(len(find_by_uuid(entries, "FE7B-D8D1")), 1)

    def test_mount_point_lookup_unescapes(self):
        entries = parse_fstab("UUID=X  /mnt/Games\\0402TB  exfat  defaults  0  0\n")
        self.assertEqual(len(find_by_mount_point(entries, "/mnt/Games 2TB")), 1)

    def test_mount_point_lookup_ignores_trailing_slash(self):
        entries = parse_fstab("UUID=X  /mnt/data  ext4  defaults  0  2\n")
        self.assertEqual(len(find_by_mount_point(entries, "/mnt/data/")), 1)

    def test_render_line_roundtrips(self):
        entry = build_entry("FE7B-D8D1", "/mnt/Games 2TB", "exfat", uid=1000, gid=1000)
        parsed = parse_fstab(entry.to_line() + "\n")[0]
        self.assertEqual(parsed.mount_point, "/mnt/Games 2TB")
        self.assertEqual(parsed.uuid, "FE7B-D8D1")
        self.assertIn("uid=1000", parsed.options)


class ValidationTest(unittest.TestCase):
    def test_rejects_relative(self):
        with self.assertRaises(ValueError):
            validate_mount_point("mnt/data")

    def test_rejects_root(self):
        with self.assertRaises(ValueError):
            validate_mount_point("/")

    def test_rejects_system_paths(self):
        for path in ("/home/miku", "/boot", "/etc/data", "/var/lib/x"):
            with self.assertRaises(ValueError, msg=path):
                validate_mount_point(path)

    def test_accepts_data_paths(self):
        self.assertEqual(validate_mount_point("/mnt/data/"), "/mnt/data")
        self.assertEqual(
            validate_mount_point("/mnt/Games 2TB"), "/mnt/Games 2TB"
        )
        self.assertEqual(validate_mount_point("/srv/data"), "/srv/data")

    def test_normalize(self):
        self.assertEqual(normalize_mount_point("/mnt/data///"), "/mnt/data")
        self.assertEqual(normalize_mount_point("/"), "/")


class OptionsTest(unittest.TestCase):
    def test_exfat_permissions(self):
        options = default_options("exfat", uid=1000, gid=1000)
        for expected in ("defaults", "nofail", "x-systemd.automount", "uid=1000", "gid=1000"):
            self.assertIn(expected, options.split(","))

    def test_ext4_has_no_uid(self):
        options = default_options("ext4", uid=1000, gid=1000).split(",")
        self.assertNotIn("uid=1000", options)
        self.assertIn("x-systemd.automount", options)

    def test_ext4_gets_fsck_pass_2(self):
        self.assertEqual(build_entry("X", "/mnt/x", "ext4").passno, 2)
        self.assertEqual(build_entry("X", "/mnt/x", "exfat").passno, 0)

    def test_no_automount(self):
        options = default_options("exfat", automount=False).split(",")
        self.assertNotIn("x-systemd.automount", options)
        self.assertIn("nofail", options)


class LsblkTest(unittest.TestCase):
    JSON = """
    {"blockdevices": [
      {"name": "nvme2n1", "path": "/dev/nvme2n1", "type": "disk",
       "fstype": null, "label": null, "uuid": null, "size": "1.8T",
       "mountpoint": null,
       "children": [
         {"name": "nvme2n1p1", "path": "/dev/nvme2n1p1", "type": "part",
          "fstype": "exfat", "label": "Games 2TB", "uuid": "FE7B-D8D1",
          "size": "1.8T", "mountpoint": null}
       ]}
    ]}
    """

    def test_flatten(self):
        devices = flatten_devices(parse_lsblk(self.JSON))
        self.assertEqual([device.name for device in devices], ["nvme2n1", "nvme2n1p1"])
        partition = devices[1]
        self.assertEqual(partition.uuid, "FE7B-D8D1")
        self.assertEqual(partition.display_name, "Games 2TB")
        self.assertIsNone(partition.mountpoint)


if __name__ == "__main__":
    unittest.main()
