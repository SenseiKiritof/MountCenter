#!/usr/bin/env bash
# Installa MountCenter in PREFIX (default /usr/local). Richiede root.
set -euo pipefail

PREFIX=${PREFIX:-/usr/local}
DESTDIR=${DESTDIR:-}
LIBDIR="${PREFIX}/lib/mountcenter"
BINDIR="${PREFIX}/bin"
APPDIR="${PREFIX}/share/applications"
POLICYDIR="/usr/share/polkit-1/actions"
APPID="io.github.senseikiritof.MountCenter"

if [[ -n "${DESTDIR}" ]]; then
    : # installazione in staging, nessun root richiesto
elif [[ $EUID -ne 0 ]]; then
    echo "Esegui con sudo: sudo ./install.sh" >&2
    exit 1
fi

install -d "${DESTDIR}${LIBDIR}/mountcenter" "${DESTDIR}${BINDIR}" \
    "${DESTDIR}${APPDIR}" "${DESTDIR}${POLICYDIR}"
install -m 0644 mountcenter/__init__.py mountcenter/core.py \
    mountcenter/app.py "${DESTDIR}${LIBDIR}/mountcenter/"
install -m 0755 mountcenter/helper.py "${DESTDIR}${LIBDIR}/mountcenter/helper.py"

cat > "${DESTDIR}${BINDIR}/mountcenter" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "${LIBDIR}")
from mountcenter.app import main
raise SystemExit(main())
EOF
chmod 0755 "${DESTDIR}${BINDIR}/mountcenter"

sed "s|@PREFIX@|${PREFIX}|g" data/mountcenter.desktop.in \
    > "${DESTDIR}${APPDIR}/mountcenter.desktop"
chmod 0644 "${DESTDIR}${APPDIR}/mountcenter.desktop"

sed "s|@HELPER@|${LIBDIR}/mountcenter/helper.py|g" data/mountcenter.policy.in \
    > "${DESTDIR}${POLICYDIR}/${APPID}.policy"
chmod 0644 "${DESTDIR}${POLICYDIR}/${APPID}.policy"

echo "Installato in ${PREFIX}. Avvia con: mountcenter"
echo "Helper privilegiato: ${LIBDIR}/mountcenter/helper.py"
echo "Policy polkit: ${POLICYDIR}/${APPID}.policy"
