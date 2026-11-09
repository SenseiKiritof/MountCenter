import json
import os
import tempfile
import unittest
from pathlib import Path

from mountcenter import helper
from mountcenter.core import build_entry, parse_fstab


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fstab = os.path.join(self.tmp.name, "fstab")
        Path(self.fstab).write_text(
            "# /etc/fstab di test\n"
            "UUID=ROOT  /  btrfs  subvol=root  0  0\n",
            encoding="utf-8",
        )

    def apply(self, **overrides):
        params = {
            "uuid": "FE7B-D8D1",
            "mount_point": "/mnt/Games 2TB",
            "fstype": "exfat",
            "uid": 1000,
            "gid": 1000,
        }
        params.update(overrides)
        entry = build_entry(**params)
        return helper.apply(
            entry, fstab_path=self.fstab, verify_device=False
        )

    def test_apply_writes_escaped_line_and_backup(self):
        result = self.apply()
        self.assertTrue(result["ok"])
        self.assertTrue(os.path.exists(result["backup"]))
        text = Path(self.fstab).read_text(encoding="utf-8")
        self.assertIn("/mnt/Games\\0402TB", text)
        self.assertIn("# /etc/fstab di test", text)
        entries = parse_fstab(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1].mount_point, "/mnt/Games 2TB")
        self.assertEqual(entries[1].fstype, "exfat")
        self.assertIn("x-systemd.automount", entries[1].options)

    def test_apply_is_atomic_and_preserves_mode(self):
        os.chmod(self.fstab, 0o640)
        self.apply()
        self.assertEqual(os.stat(self.fstab).st_mode & 0o777, 0o640)
        leftovers = [name for name in os.listdir(self.tmp.name) if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_duplicate_uuid_is_rejected(self):
        self.apply()
        with self.assertRaises(helper.HelperError):
            self.apply(mount_point="/mnt/altro")

    def test_duplicate_mount_point_is_rejected(self):
        self.apply()
        with self.assertRaises(helper.HelperError):
            self.apply(uuid="AAA-BBB")

    def test_second_apply_does_not_touch_fstab(self):
        self.apply()
        before = Path(self.fstab).read_bytes()
        with self.assertRaises(helper.HelperError):
            self.apply(mount_point="/mnt/altro")
        self.assertEqual(Path(self.fstab).read_bytes(), before)

    def test_remove_preserves_other_lines_and_comments(self):
        self.apply()
        result = helper.remove(uuid="fe7b-d8d1", fstab_path=self.fstab)
        self.assertTrue(result["ok"])
        text = Path(self.fstab).read_text(encoding="utf-8")
        self.assertEqual(
            text,
            "# /etc/fstab di test\nUUID=ROOT  /  btrfs  subvol=root  0  0\n",
        )

    def test_remove_unknown_uuid(self):
        with self.assertRaises(helper.HelperError):
            helper.remove(uuid="NOPE", fstab_path=self.fstab)

    def test_status_lists_entries(self):
        self.apply()
        result = helper.status(fstab_path=self.fstab)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["entries"]), 2)
        self.assertTrue(result["entries"][1]["automount"])
        self.assertEqual(result["entries"][1]["mount_point"], "/mnt/Games 2TB")

    def test_cli_apply_and_status(self):
        code = helper.main(
            [
                "apply",
                "--uuid",
                "AAAA-BBBB",
                "--mount-point",
                "/mnt/cli data",
                "--fstype",
                "exfat",
                "--fstab",
                self.fstab,
                "--skip-device-check",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("/mnt/cli\\040data", Path(self.fstab).read_text(encoding="utf-8"))
        self.assertEqual(helper.main(["status", "--fstab", self.fstab]), 0)

    def test_cli_error_is_json(self):
        code = helper.main(
            ["apply", "--uuid", "X", "--mount-point", "/", "--fstype", "exfat",
             "--fstab", self.fstab, "--skip-device-check"]
        )
        self.assertEqual(code, 1)


class HelperJsonTest(unittest.TestCase):
    def test_status_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fstab = os.path.join(tmp, "fstab")
            Path(fstab).write_text(
                "UUID=FE7B-D8D1  /mnt/Games\\0402TB  exfat  defaults  0  0\n",
                encoding="utf-8",
            )
            payload = json.loads(json.dumps(helper.status(fstab_path=fstab)))
            self.assertEqual(payload["entries"][0]["mount_point"], "/mnt/Games 2TB")


if __name__ == "__main__":
    unittest.main()
