#!/usr/bin/env bash
#
# setup-automount.sh
# Configura il mount automatico di un disco esterno su Fedora tramite
# /etc/fstab, usando UUID e systemd automount (con opzione "nofail").
#
# Uso: sudo ./setup-automount.sh

set -euo pipefail

# --- Controllo permessi root ---
if [[ $EUID -ne 0 ]]; then
    echo "Questo script deve essere eseguito con sudo/root."
    echo "Esempio: sudo $0"
    exit 1
fi

echo "=== Dispositivi a blocchi disponibili ==="
echo
lsblk -f -o NAME,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINT
echo

# --- Selezione del device ---
read -rp "Inserisci il nome della partizione da montare (es. sdb1, senza /dev/): " DEV_NAME
DEVICE="/dev/${DEV_NAME}"

if [[ ! -b "$DEVICE" ]]; then
    echo "Errore: $DEVICE non è un device a blocchi valido."
    exit 1
fi

# --- Recupero UUID e filesystem ---
UUID=$(blkid -s UUID -o value "$DEVICE" || true)
FSTYPE=$(blkid -s TYPE -o value "$DEVICE" || true)

if [[ -z "$UUID" ]]; then
    echo "Errore: impossibile determinare l'UUID di $DEVICE."
    exit 1
fi

if [[ -z "$FSTYPE" ]]; then
    echo "Attenzione: impossibile determinare automaticamente il filesystem."
    read -rp "Inserisci manualmente il filesystem (es. ext4, ntfs3, exfat, vfat): " FSTYPE
fi

echo
echo "Device selezionato: $DEVICE"
echo "UUID:               $UUID"
echo "Filesystem:          $FSTYPE"
echo

# --- Punto di mount ---
DEFAULT_LABEL=$(blkid -s LABEL -o value "$DEVICE" || true)
DEFAULT_NAME=${DEFAULT_LABEL:-$DEV_NAME}
read -rp "Punto di montaggio [/mnt/${DEFAULT_NAME}]: " MOUNT_POINT
MOUNT_POINT=${MOUNT_POINT:-/mnt/${DEFAULT_NAME}}

# --- Opzioni extra per filesystem NTFS/exFAT/FAT ---
EXTRA_OPTS=""
if [[ "$FSTYPE" =~ ^(ntfs|ntfs3|exfat|vfat)$ ]]; then
    read -rp "Aggiungere uid=1000,gid=1000 per i permessi utente? [S/n]: " ADD_UID
    ADD_UID=${ADD_UID:-S}
    if [[ "$ADD_UID" =~ ^[Ss]$ ]]; then
        EXTRA_OPTS=",uid=1000,gid=1000"
    fi
fi

# fstab separa i campi con whitespace: spazi e tab nel path vanno escapati
FSTAB_MOUNT=$(printf '%s' "$MOUNT_POINT" | sed -e 's/\\/\\\\/g' -e 's/ /\\040/g' -e 's/\t/\\011/g')

# fsck solo per filesystem che lo supportano
FSCK_PASS=0
case "$FSTYPE" in
    ext2|ext3|ext4) FSCK_PASS=2 ;;
esac

OPTIONS="defaults,nofail,x-systemd.automount${EXTRA_OPTS}"
FSTAB_LINE="UUID=${UUID}  ${FSTAB_MOUNT}  ${FSTYPE}  ${OPTIONS}  0  ${FSCK_PASS}"

# --- Controllo duplicati in fstab, prima di riepilogo e scrittura ---
if awk -v uuid="$UUID" '
    /^[[:space:]]*#/ { next }
    tolower($1) == "uuid=" tolower(uuid) { found = 1 }
    END { exit !found }' /etc/fstab; then
    echo "Errore: l'UUID $UUID è già presente in /etc/fstab. Nessuna modifica effettuata."
    exit 1
fi

if mnt="$MOUNT_POINT" esc="$FSTAB_MOUNT" awk '
    /^[[:space:]]*#/ { next }
    $2 == ENVIRON["mnt"] || $2 == ENVIRON["esc"] { found = 1 }
    END { exit !found }' /etc/fstab; then
    echo "Errore: il punto di montaggio $MOUNT_POINT è già presente in /etc/fstab. Nessuna modifica effettuata."
    exit 1
fi

echo
echo "=== Riepilogo operazioni da eseguire ==="
echo "1. Creazione punto di montaggio: $MOUNT_POINT"
echo "2. Backup di /etc/fstab in /etc/fstab.bak.<timestamp>"
echo "3. Aggiunta a /etc/fstab della riga:"
echo "   $FSTAB_LINE"
echo

read -rp "Confermi l'esecuzione? [s/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Ss]$ ]]; then
    echo "Operazione annullata. Nessuna modifica effettuata."
    exit 0
fi

# --- Esecuzione ---
mkdir -p "$MOUNT_POINT"

BACKUP_FILE="/etc/fstab.bak.$(date +%Y%m%d%H%M%S)"
cp /etc/fstab "$BACKUP_FILE"
echo "Backup creato: $BACKUP_FILE"

echo "$FSTAB_LINE" >> /etc/fstab
echo "Riga aggiunta a /etc/fstab."

systemctl daemon-reload

# Verifica che systemd abbia generato l'unità dalla riga fstab
MOUNT_UNIT=$(systemd-escape --path --suffix=mount "$MOUNT_POINT")
if [[ "$(systemctl show -p LoadState "$MOUNT_UNIT" | cut -d= -f2)" != "loaded" ]]; then
    echo "Errore: riga fstab non valida, unità $MOUNT_UNIT non generata."
    echo "Ripristina il backup con: sudo cp $BACKUP_FILE /etc/fstab"
    exit 1
fi

echo
read -rp "Vuoi testare subito il mount con 'mount -a'? [S/n]: " TEST_MOUNT
TEST_MOUNT=${TEST_MOUNT:-S}
if [[ "$TEST_MOUNT" =~ ^[Ss]$ ]]; then
    if mount -a; then
        echo "Mount riuscito. Verifica con: ls $MOUNT_POINT"
    else
        echo "Errore durante il mount. Controlla /etc/fstab e, se necessario, ripristina il backup con:"
        echo "  sudo cp $BACKUP_FILE /etc/fstab"
        exit 1
    fi
fi

echo
echo "Configurazione completata. Il disco verrà montato automaticamente al prossimo avvio."
