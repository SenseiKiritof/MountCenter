Name:           mountcenter
Version:        0.1.1
Release:        1%{?dist}
Summary:        Configure systemd automount entries for disks
License:        GPL-3.0-or-later
URL:            https://github.com/SenseiKiritof/MountCenter
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita >= 1.5
Requires:       polkit
Requires:       util-linux

%description
A GTK4 application and a small privileged helper to configure the automatic
mount of internal and external disks through /etc/fstab, using UUIDs,
nofail and systemd automount. Mount points with spaces are escaped, duplicate
UUIDs and mount points are refused, every write is backed up, and the
generated systemd mount unit is verified before the operation is confirmed.

%prep
%autosetup

%build
# Nothing to build: the application and the helper are Python.

%install
make install DESTDIR=%{buildroot} PREFIX=%{_prefix}

%files
%license LICENSE
%doc README.md
%{_bindir}/mountcenter
%{_prefix}/lib/mountcenter
%{_datadir}/applications/mountcenter.desktop
%{_datadir}/polkit-1/actions/io.github.senseikiritof.MountCenter.policy

%changelog
* Mon Nov 09 2026 senseikiritof <tonifede98@gmail.com> - 0.1.1-1
- Automount check icon in the disk list
- Compatibility tests on Debian, Ubuntu, Arch and openSUSE

* Mon Nov 09 2026 senseikiritof <tonifede98@gmail.com> - 0.1.0-1
- First package: GTK4 interface, privileged helper, first-launch polkit trust
