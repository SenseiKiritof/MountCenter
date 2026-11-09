import os
import unittest

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    raise unittest.SkipTest("serve un display (xvfb) per il test della GUI")

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import GLib
except (ImportError, ValueError) as error:  # pragma: no cover - container senza GTK
    raise unittest.SkipTest(f"GTK4/libadwaita non disponibili: {error}")

from mountcenter.app import MountCenterApp  # noqa: E402


class AppSmokeTest(unittest.TestCase):
    def test_window_builds_and_lists_devices(self):
        app = MountCenterApp()
        seen = {}

        def on_activate(application):
            window = application.get_active_window()
            seen["window"] = window
            if window is not None:
                seen["rows"] = window.device_list.get_row_at_index(0)
            GLib.idle_add(application.quit)

        app.connect_after("activate", on_activate)
        app.run([])
        self.assertIsNotNone(seen.get("window"))
        self.assertIsNotNone(
            seen.get("rows"),
            "la lista dischi deve contenere almeno una riga (anche segnaposto)",
        )


if __name__ == "__main__":
    unittest.main()
