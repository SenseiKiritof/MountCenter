#!/usr/bin/env python3
"""GTK4/libadwaita interface for MountCenter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from mountcenter.core import (  # noqa: E402
    USER_PERM_FSTYPES,
    Device,
    build_entry,
    find_by_uuid,
    flatten_devices,
    parse_fstab,
    parse_lsblk,
)

HELPER = Path(__file__).with_name("helper.py")
FSTAB = Path("/etc/fstab")
APP_ID = "io.github.senseikiritof.MountCenter"


def _read_fstab() -> str:
    try:
        return FSTAB.read_text(encoding="utf-8")
    except OSError:
        return ""


def _list_devices() -> list[Device]:
    try:
        result = subprocess.run(
            [
                "lsblk",
                "-J",
                "-o",
                "NAME,PATH,TYPE,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINT",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    try:
        return flatten_devices(parse_lsblk(result.stdout))
    except (ValueError, KeyError):
        return []


class MountCenterWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application):
        super().__init__(application=application, title="MountCenter")
        self.set_default_size(1000, 680)
        self.fstab_entries = []

        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(
                title="MountCenter",
                subtitle="Mount automatici dei dischi",
            )
        )
        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text("Rileggi dischi e /etc/fstab")
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_end(refresh)

        self.toast_overlay = Adw.ToastOverlay()
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(380)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)
        paned.set_start_child(self._build_device_list())
        paned.set_end_child(self._build_detail())

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(paned)
        self.toast_overlay.set_child(toolbar_view)
        self.set_content(self.toast_overlay)

        self.reload()

    def _build_device_list(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self.device_list = Gtk.ListBox()
        self.device_list.add_css_class("navigation-sidebar")
        self.device_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.device_list.connect("row-selected", self._on_row_selected)
        scrolled.set_child(self.device_list)
        return scrolled

    def _build_detail(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        self.detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.detail_box.set_margin_top(24)
        self.detail_box.set_margin_bottom(24)
        self.detail_box.set_margin_start(24)
        self.detail_box.set_margin_end(24)
        scrolled.set_child(self.detail_box)
        self._show_placeholder()
        return scrolled

    def _clear_detail(self) -> None:
        child = self.detail_box.get_first_child()
        while child is not None:
            self.detail_box.remove(child)
            child = self.detail_box.get_first_child()

    def _show_placeholder(self) -> None:
        self._clear_detail()
        label = Gtk.Label(
            label="Seleziona un disco per configurarne il mount automatico."
        )
        label.add_css_class("dim-label")
        label.set_wrap(True)
        self.detail_box.append(label)

    def reload(self) -> None:
        self.fstab_entries = parse_fstab(_read_fstab())
        self.device_list.remove_all()
        self._show_placeholder()

        candidates = [
            device
            for device in _list_devices()
            if device.uuid and device.fstype and device.type in {"part", "disk"}
        ]
        if not candidates:
            row = Adw.ActionRow(
                title="Nessun disco trovato",
                subtitle="Collega un disco e premi Aggiorna.",
            )
            row.set_activatable(False)
            self.device_list.append(row)
            return

        for device in candidates:
            configured = find_by_uuid(self.fstab_entries, device.uuid or "")
            details = [device.fstype or "?", device.size or "", device.path]
            if configured:
                details.append(f"fstab: {configured[0].mount_point}")
            elif device.mountpoint:
                details.append(f"montato in {device.mountpoint}")
            row = Adw.ActionRow(
                title=device.display_name,
                subtitle=" · ".join(detail for detail in details if detail),
            )
            row.set_activatable(True)
            row.device = device
            self.device_list.append(row)

    def _on_row_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None or not hasattr(row, "device"):
            return
        self._show_device(row.device)

    def _show_device(self, device: Device) -> None:
        self._clear_detail()
        configured = find_by_uuid(self.fstab_entries, device.uuid or "")

        title = Gtk.Label(label=device.display_name)
        title.add_css_class("title-1")
        title.set_xalign(0)
        subtitle = Gtk.Label(
            label=f"{device.path} · {device.fstype or '?'} · {device.size or ''} · UUID {device.uuid}"
        )
        subtitle.add_css_class("dim-label")
        subtitle.set_xalign(0)
        subtitle.set_wrap(True)
        self.detail_box.append(title)
        self.detail_box.append(subtitle)

        group = Adw.PreferencesGroup()
        group.set_title("Mount automatico")
        group.set_description(
            "La voce viene aggiunta a /etc/fstab con nofail e x-systemd.automount."
        )

        self.mount_row = Adw.EntryRow(title="Punto di montaggio")
        default_name = device.label or device.name
        self.mount_row.set_text(
            configured[0].mount_point if configured else f"/mnt/{default_name}"
        )
        self.mount_row.connect("notify::text", lambda *_: self._update_preview(device))
        group.add(self.mount_row)

        self.automount_row = Adw.SwitchRow(title="Monta automaticamente")
        self.automount_row.set_subtitle(
            "x-systemd.automount: monta al primo accesso, senza bloccare l'avvio"
        )
        self.automount_row.set_active(
            configured[0].automount if configured else True
        )
        self.automount_row.connect("notify::active", lambda *_: self._update_preview(device))
        group.add(self.automount_row)

        self.perm_row = Adw.SwitchRow(title="Permessi utente")
        self.perm_row.set_subtitle(f"uid={os.getuid()}, gid={os.getgid()}")
        self.perm_row.set_visible(device.fstype in USER_PERM_FSTYPES)
        self.perm_row.set_active(True)
        self.perm_row.connect("notify::active", lambda *_: self._update_preview(device))
        group.add(self.perm_row)

        self.detail_box.append(group)

        preview_caption = Gtk.Label(label="Riga fstab")
        preview_caption.add_css_class("heading")
        preview_caption.set_xalign(0)
        self.detail_box.append(preview_caption)

        self.preview = Gtk.Label()
        self.preview.add_css_class("monospace")
        self.preview.add_css_class("dim-label")
        self.preview.set_selectable(True)
        self.preview.set_wrap(True)
        self.preview.set_xalign(0)
        self.detail_box.append(self.preview)

        self.apply_button = Gtk.Button()
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.set_halign(Gtk.Align.END)
        self.apply_button.connect("clicked", lambda *_: self._apply(device))
        self.detail_box.append(self.apply_button)

        if configured:
            self.apply_button.set_label("Già configurato")
            self.apply_button.set_sensitive(False)
            self.preview.set_text(
                f"Riga {configured[0].line_no}: {configured[0].to_line()}"
            )
        else:
            self.apply_button.set_label("Applica")
            self._update_preview(device)

    def _entry_for(self, device: Device):
        permissions = self.perm_row.get_active() and device.fstype in USER_PERM_FSTYPES
        return build_entry(
            device.uuid or "",
            self.mount_row.get_text().strip(),
            device.fstype or "",
            uid=os.getuid() if permissions else None,
            gid=os.getgid() if permissions else None,
            automount=self.automount_row.get_active(),
        )

    def _update_preview(self, device: Device) -> None:
        try:
            entry = self._entry_for(device)
        except ValueError as error:
            self.preview.set_text(str(error))
            self.apply_button.set_sensitive(False)
            return
        self.preview.set_text(entry.to_line())
        self.apply_button.set_sensitive(True)

    def _apply(self, device: Device) -> None:
        try:
            entry = self._entry_for(device)
        except ValueError as error:
            self._toast(str(error))
            return

        permissions = self.perm_row.get_active() and device.fstype in USER_PERM_FSTYPES
        command = [
            "pkexec",
            sys.executable,
            str(HELPER),
            "apply",
            "--uuid",
            device.uuid or "",
            "--mount-point",
            entry.mount_point,
            "--fstype",
            entry.fstype,
        ]
        if permissions:
            command += ["--uid", str(os.getuid()), "--gid", str(os.getgid())]
        if not self.automount_row.get_active():
            command.append("--no-automount")

        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError as error:
            self._alert("Impossibile avviare l'helper", str(error))
            return

        payload: dict = {}
        try:
            payload = json.loads(result.stdout.strip() or "{}")
        except ValueError:
            payload = {}

        if result.returncode == 0 and payload.get("ok"):
            self._toast("Configurazione applicata.")
            self.reload()
            return
        message = (
            payload.get("error")
            or result.stderr.strip()
            or f"L'operazione è terminata con codice {result.returncode}."
        )
        self._alert("Applicazione non riuscita", message)

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=message))

    def _alert(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.present(self)


class MountCenterApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            window = MountCenterWindow(self)
        window.present()


def main(argv: list[str] | None = None) -> int:
    app = MountCenterApp()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
