# AGENTS.md - youtube-transcripts

Aplica a `youtube-transcripts/**` ademas del `AGENTS.md` raiz. No contradice la
politica del repositorio; solo anade reglas locales.

## Reglas

- **Python >= 3.12 con uv** (HARD): dependencias declaradas en `pyproject.toml` y
  fijadas en `uv.lock`. Runtime: `mcp`, `yt-dlp`, `youtube-transcript-api` y
  `fpdf2` (PDF; aprobado por el usuario el 2026-11-12). Anadir
  otra dependencia de runtime requiere aprobacion.
- **No reinventar** (CONTROLLED): el listado de canales lo hace `yt-dlp` y las
  transcripciones `youtube-transcript-api`. Este proyecto solo aporta cache,
  seleccion de idioma, busqueda, exportacion y la capa MCP/CLI.
- **Logica en `core.py`, sin red en los tests** (CONTROLLED): la red entra por los
  parametros inyectables `lister`, `fetcher`, `enricher` y `sub_fetcher`. `server.py`
  y `cli.py` son capas finas sobre `core`; `text.py` limpia y arma parrafos;
  `search.py` busca en YouTube (inyectable `searcher`). `document.py` arma el documento MD/PDF. `topic.py` busca candidatos
  por tema; `catalog.py` catalogo, listas de seleccion y procesamiento final.
- **Sin API key ni credenciales** (HARD): no usar la YouTube Data API ni cuentas de
  Google; todo va por paginas publicas via `yt-dlp`/`youtube-transcript-api`.
- **JSON = verdad, SQLite = indice** (HARD): `index.py` (FTS5, biblioteca estandar)
  es derivado y reconstruible con `rebuild_index`; nunca guardar datos solo en el indice.
- **Respuestas MCP acotadas** (CONTROLLED): las herramientas devuelven resumenes y
  paginan el texto (`max_chars`/`offset`); ninguna vuelca un canal entero al contexto.
- **Escrituras atomicas y reanudables** (HARD): la cache se escribe con
  archivo temporal + `os.replace` y se guarda tras cada video.
- **Bloqueo de IP = parar** (HARD): ante `IpBlocked`/`RequestBlocked` se detiene la
  descarga y se informa en `blocked`; no reintentar en bucle.
- **Datos fuera de git**: la cache vive en `YT_TRANSCRIPTS_DIR` (por defecto
  `~/.yt-channel-transcripts`); `data/` esta ignorado.

## Comandos

- `uv sync` - instalar.
- `uv run pytest -q` - tests unitarios e integracion (servidor por stdio), sin red.
- `uv run pytest -q -m network --network` - prueba real contra YouTube.
- `uv run yt-transcripts --help` - CLI; `uv run yt-transcripts-mcp` - servidor MCP.
