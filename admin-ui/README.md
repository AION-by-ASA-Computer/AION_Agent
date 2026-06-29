# AION Admin UI (Next.js)

Interfaccia amministrativa **ufficiale** per AION Agent. La vecchia pagina statica in `static/admin/` è deprecata (su `/admin/dashboard` c’è solo un avviso).

## Requisiti

- Backend FastAPI in esecuzione (es. `uvicorn src.api.main:app --port 8001`)

## Configurazione

Crea `admin-ui/.env.local` (opzionale):

```env
NEXT_PUBLIC_AION_API_URL=http://localhost:8001
```

Se omesso, il client usa `http://localhost:8001`.

## Avvio

```bash
cd admin-ui
npm install
npm run dev
```

Apri [http://localhost:3870](http://localhost:3870) (in dev locale senza prefisso `/admin`; in Docker/Caddy l'app è su `/admin`).

**Importante:** l'admin-ui non include l'API. Avvia il backend in un altro terminale:

```bash
./scripts/dev-api.sh   # oppure: uvicorn src.api.main:app --port 8001
```

## Funzionalità

| Route | Contenuto |
|-------|-----------|
| `/` | Dashboard e statistiche |
| `/profiles` | Profili agente |
| `/skills` | Skill Markdown |
| `/hub` | Registry MCP |
| `/memory` | Query memory + LTM MemPalace |
| `/profile-memory` | File **SOUL / MEMORY / USER** per profilo (`/admin/profile-memory/*`) |
| `/security` | Audit sicurezza |
| `/settings` | Impostazioni |

Per le route **profile-memory**, se nel backend è impostato `AION_ADMIN_MEMORY_TOKEN`, inserisci lo stesso token nella pagina (salvato in `sessionStorage`).

## Build produzione

```bash
npm run build
npm start
```

Serve un reverse proxy che inoltri le richieste API al processo FastAPI se UI e API sono su host diversi (CORS è già `*` sul backend di default).
