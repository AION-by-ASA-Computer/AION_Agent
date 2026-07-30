# config_proprietary — skill con licenza di terze parti (solo locale)

Questa cartella **non viene pubblicata su GitHub**. Contiene skill office (es. Anthropic
`docx`, `pdf`, `pptx`, `xlsx`) che non possono essere ridistribuite nel repo open source.

## Policy

**Mai** mettere `docx`, `pdf`, `pptx`, `xlsx` sotto `config_std/` — finirebbero nel repo OSS. Solo qui, in
`config_proprietary/skills/` (gitignored).

CI esegue `scripts/check_config_std_no_proprietary_skills.py` su ogni push/PR.

## Setup iniziale (una tantum)

Se hai ancora i pacchetti in `config_std/skills/` (clone vecchio o prima della migrazione):

```bash
python scripts/migrate_proprietary_skills_from_std.py
```

Oppure copia manualmente le directory elencate in `manifest.yaml` sotto `skills/`.

## Sync verso `config/` (runtime)

Dopo `sync_config` da `config_std/`, sincronizza le skill proprietarie:

```bash
python scripts/sync_proprietary_config.py
# oppure con sovrascrittura:
python scripts/sync_proprietary_config.py --force
```

`setup-aion-env.sh` / `upgrade-aion.sh` chiamano questo script **solo se**
`config_proprietary/skills/` esiste.

## Struttura attesa

```
config_proprietary/
  manifest.yaml      # elenco skill (committato)
  README.md          # questa guida (committato)
  skills/            # gitignored — contenuto proprietario
    docx/
    pdf/
    pptx/
    xlsx/
```

Senza `skills/`, i profili che referenziano `docx` / `pptx` / … funzionano ma
`skill_view` su quelle skill non troverà i pacchetti finché non esegui il sync.
