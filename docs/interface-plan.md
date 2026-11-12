# Piano interfaccia grafica — MountCenter

Stato: implementato quasi per intero. Core, helper privilegiato, GUI
(GTK4/libadwaita) con scelta mount all'avvio o al primo accesso, primo avvio e
autorizzazione polkit ricordata, install script, RPM e workflow di release sono
presenti. Restano: rimozione e stato automount nella GUI, rifiniture della
policy polkit, pacchetti Debian/Arch.

Obiettivo: sostituire la sessione interattiva da terminale con una GUI GTK4 /
libadwaita che permetta di scegliere una partizione, configurare il mount
automatico e vedere lo stato reale, mantenendo le garanzie di sicurezza dello
script bash attuale.

## 1. Vincoli e scelte di fondo

- La GUI gira come utente normale. Ogni scrittura su `/etc/fstab` passa da un
  helper privilegiato invocato con `pkexec`, non da `sudo` dentro la GUI.
- Una sola fonte di verità per la logica: le regole oggi nello script bash
  (escape del path, controllo duplicati, backup, verifica unità systemd)
  vengono portate in un modulo Python riutilizzato da helper e test.
- Lo script bash resta disponibile per uso headless durante la transizione e
  viene rimosso quando l'helper copre tutte le operazioni.
- Target: Fedora con Python 3.14, GTK 4.22, libadwaita 1.9 (già installati).

## 2. Architettura

```
mountcenter/                  pacchetto Python
  core.py                     logica pura, senza root:
                              - parse lsblk -J, parse fstab
                              - escape/unescape campi fstab
                              - costruzione riga fstab
                              - controllo duplicati UUID / mount point
  helper.py                   CLI privilegiata (root):
                              - apply / remove / status
                              - backup, scrittura atomica, daemon-reload
                              - verifica LoadState dell'unità generata
  app.py                      applicazione GTK4 + libadwaita
  widgets/
    device-list.ui            lista dischi e partizioni
    device-detail.ui          dettaglio e opzioni
    confirm-dialog.ui         anteprima riga fstab e conferma
  data/
    mountcenter.desktop
    mountcenter.metainfo.xml
docs/interface-plan.md
tests/test_core.py            unittest stdlib, nessuna dipendenza
tests/test_helper.py          apply/remove su fstab temporaneo
```

Flusso di una modifica:

1. La GUI legge lo stato con `lsblk -J` e `/etc/fstab` (sola lettura).
2. L'utente sceglie partizione, mount point e opzioni.
3. La GUI mostra l'anteprima esatta della riga fstab.
4. Alla conferma, la GUI invoca
   `pkexec mountcenter-helper apply --json` passando i parametri su stdin.
5. L'helper rivalida tutto lato root (non si fida dell'input della GUI),
   crea il backup, scrive, esegue `systemctl daemon-reload` e verifica che
   l'unità `.mount` sia `loaded`.
6. La GUI mostra esito e stato aggiornato; su errore indica il backup da
   ripristinare.

Regole di sicurezza dell'helper:

- accetta solo UUID esistenti su device a blocchi reali (`blkid`), mai path
  arbitrari;
- mount point normalizzato, assoluto, senza `..`, fuori da `/`, `/boot`,
  `/home`, `/etc` e dalle altre destinazioni di sistema;
- opzioni whitelist: `defaults`, `nofail`, `x-systemd.automount`, `uid=`,
  `gid=`, `fmask=`, `dmask=`, `umask=`, `ro`;
- scrittura atomica: file temporaneo nella stessa directory, `fsync`, rename;
- backup con timestamp prima di ogni scrittura;
- lock con `flock` per evitare due istanze contemporanee;
- nessuna shell interpolation: si passano argomenti, non stringhe di comando.

## 3. Esperienza utente

Finestra principale:

- lista raggruppata per disco fisico, con nome, label, dimensione,
  filesystem e indicatore di stato (montato, automount attivo, assente da
  fstab, montato da udisks);
- ricerca per nome, label o UUID;
- pulsante "Aggiorna" e refresh automatico al cambio di stato rilevante;
- pulsante "+" per aggiungere un mount automatico.

Dettaglio partizione:

- riepilogo: UUID, filesystem, dimensione, label, device;
- campo mount point con default `/mnt/<label>`, validazione live;
- switch "Mount automatico all'avvio" (`x-systemd.automount`);
- switch "Non bloccare l'avvio se assente" (`nofail`, attivo e non
  disattivabile senza avviso);
- permessi utente solo per exfat/vfat/ntfs: uid/gid precompilati con
  l'utente della sessione;
- `ro` come opzione avanzata;
- anteprima della riga fstab aggiornata in tempo reale;
- pulsante "Applica" disabilitato finché il mount point non è valido o è
  duplicato.

Gestione delle voci esistenti:

- vista "Configurati da MountCenter" con stato dell'unità systemd;
- azioni: smonta, disattiva automount, rimuovi voce (con backup);
- voci scritte a mano: sola lettura, con badge "manuale" e link al file.

Errore tipico da rendere visibile: la riga fstab non valida per spazi non
escapati, che oggi systemd ignora silenziosamente. La GUI deve bloccare
l'anteprima prima della conferma e mostrare l'anteprima escapata.

## 4. Fasi

### Fase 0 — Pulizia repo (mezza giornata)

- `.gitignore` per `__pycache__/`, `.venv/`, `build/`.
- Licenza, se da pubblicare (GPL-3.0 coerente con un tool desktop Fedora).
- Rinominare lo script in `mountcenter.sh` o spostarlo in `legacy/` quando
  arriva l'helper.

### Fase 1 — Core testabile (1–2 giorni)

- Portare in `core.py` le funzioni pure: escape, unescape, parsing fstab,
  parsing `lsblk -J`, costruzione riga, duplicati.
- Test `unittest` sui casi: spazio nel path, tab, UUID maiuscolo/minuscolo,
  mount point duplicato, riga commentata, riga malformata.
- Criterio di uscita: `python3 -m unittest` verde, nessuna dipendenza esterna.

### Fase 2 — Helper privilegiato (2 giorni)

- `helper.py` con `apply`, `remove`, `status`.
- Backup, scrittura atomica, `daemon-reload`, verifica `LoadState`.
- Test su fstab temporaneo tramite parametro `--fstab PATH` (solo test).
- Prova manuale in VM o con `systemd-run`; nessun test automatico che
  scriva il vero `/etc/fstab`.
- Criterio di uscita: aggiunta e rimozione idempotenti, errore chiaro su
  duplicati e su unità non generata.

### Fase 3 — GUI minima (3–4 giorni)

- Finestra con lista devices e dettaglio, anteprima fstab, conferma.
- Invocazione `pkexec` con output JSON dal helper.
- Stati di caricamento, errore e successo.
- Criterio di uscita: configurare da GUI un disco exfat con spazio nel nome,
  riavviare e accedere al mount point; la GUI riflette lo stato corretto.

### Fase 4 — Packaging (2 giorni)

- File `.desktop`, metainfo AppStream, icona.
- Policy polkit dedicata al posto di `pkexec` generico, se si vuole un
  prompt più chiaro.
- SPEC RPM o script `install.sh`; escluso Flatpak, non adatto a modificare
  `/etc/fstab` di sistema.
- Criterio di uscita: installazione pulita su Fedora, avvio dal menu.

### Fase 5 — Rifiniture (dopo)

- Rimozione voci, smontaggio, disattivazione automount.
- Notifica quando un mount fallisce al boot (lettura journal).
- Supporto btrfs subvolumi, solo se richiesto.

## 5. Rischi e domande aperte

- `pkexec` mostra un prompt generico "Authentication is required": la policy
  polkit nella fase 4 lo rende esplicito.
- Testare scritture su fstab reale è rischioso: serve una VM o un
  `systemd-nspawn` con fstab dedicato.
- Deduplicare la logica bash senza rompere l'uso headless: decidere se lo
  script diventa un wrapper dell'helper o viene rimosso.
- La GUI deve gestire dischi già montati da udisks/GNOME: evitare doppio
  mount e conflitti sul mount point.
- Localizzazione: italiano e inglese, o solo italiano in prima iterazione.

## 6. Ordine di lavoro consigliato

1. Fase 1 (core) e Fase 2 (helper): la GUI non serve finché la logica
   privilegiata non è solida e testata.
2. Fase 3 (GUI minima) su un solo flusso: aggiungi mount automatico.
3. Fase 4 (packaging) quando il flusso singolo è stabile.
4. Fase 5 solo dopo uso reale.

Stima complessiva: 8–10 giorni di lavoro effettivo, esclusa la fase 5.
