# youtube-transcripts

Servidor MCP y CLI para **buscar canales y videos en YouTube**, obtener **titulo, enlace,
descripcion y transcripcion** de los videos de un canal, guardarlos en una cache local,
**filtrarlos por titulo y descripcion**, buscar dentro de lo hablado y entregar el
resultado como **documento Markdown o PDF** para otro LLM (o para que el mismo lo analice).

**No necesita API key de YouTube ni cuenta de Google**: usa las mismas paginas publicas
que la web, a traves de `yt-dlp` y `youtube-transcript-api`.

## Por que existe (y que NO reinventa)

Antes de escribirlo se revisaron los proyectos open source existentes (noviembre 2026):

| Proyecto | Que hace | Por que no basta solo |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Lista los videos de un canal y sus metadatos | No es MCP; no gestiona transcripciones como texto |
| [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | Baja la transcripcion de un video, sin API key | Un video a la vez; sin nocion de canal ni cache |
| [yt-mcp-server](https://github.com/PodevynLoris/youtube-mcp-server) | MCP con `get_channel_videos`, `get_transcript`, busqueda en canal | Segun su README: sin cache local ni exportacion; cada transcripcion completa se pide a YouTube y entra al contexto del modelo |
| [YTScribe](https://github.com/dparedesi/YTScribe) | CLI que archiva canales a Markdown | No es MCP; resume con APIs de pago |
| [yt-dlp-transcripts](https://pypi.org/project/yt-dlp-transcripts/) | Canal -> CSV | No es MCP; sin reanudacion |
| [transcriptor-mcp](https://github.com/samson-art/transcriptor-mcp) | MCP con playlists, varias plataformas, Whisper opcional | No acepta canales (solo playlists); cache con Redis; Whisper requiere servidor aparte |
| [rayhanasyraff/youtube-transcript-mcp](https://github.com/rayhanasyraff/youtube-transcript-mcp) | Whisper local si no hay subtitulos, cache SQLite | Un video a la vez; proyecto muy pequeno (fork, 4 commits) |
| [youtube-research-mcp](https://github.com/BK927/youtube-research-mcp) | Comentarios, busqueda, tendencias | Listar un canal exige API key; cache solo en memoria |
| [Tube Archivist](https://github.com/tubearchivist/tubearchivist) | Archivo completo con busqueda en subtitulos | Descarga los videos enteros y requiere Elasticsearch (~4 GB RAM); no es MCP |

Decision: **reutilizar** `yt-dlp` (listado, metadatos y subtitulos de respaldo) y
`youtube-transcript-api` (transcripciones), que son las piezas maduras, y escribir solo
la capa fina que faltaba:

- cache en disco **incremental y reanudable** (no se pide dos veces lo ya bajado; un corte
  o un bloqueo de IP no pierde nada) y **listado incremental**: tras recorrer el canal una
  vez, solo se piden las paginas con videos nuevos,
- **respaldo automatico**: si `youtube-transcript-api` falla o lo bloquean, se intentan los
  subtitulos via `yt-dlp`,
- **indice SQLite FTS5** (incluido en Python, sin dependencias): filtrar por titulo,
  descripcion, tags, fecha y duracion, y buscar en lo hablado por relevancia, sin tildes,
  con frases, prefijos y OR/NOT,
- transcripciones **limpias en parrafos** con `[minuto]` y capitulos, para que el modelo
  pueda citar,
- herramientas MCP que devuelven **resumenes** y paginan el texto, para no llenar el
  contexto del modelo con miles de palabras que no pidio.

Si solo necesitas consultar un video suelto de vez en cuando, `yt-mcp-server` tambien sirve
(`claude mcp add youtube -- uvx yt-mcp-server`).

## Instalacion

Requiere [uv](https://docs.astral.sh/uv/). No necesita API key de YouTube.

```bash
cd youtube-transcripts
uv sync
uv run yt-transcripts --help
```

Para tenerlo disponible fuera del repo (independiente de la rama activa):

```bash
uv tool install ./youtube-transcripts
```

### Registrarlo como MCP

Claude Code (todos los proyectos):

```bash
claude mcp add youtube-transcripts --scope user -- yt-transcripts-mcp
```

Otros clientes (Claude Desktop, Cursor, etc.), en su `mcpServers`:

```json
{
  "youtube-transcripts": {
    "command": "uv",
    "args": ["--directory", "C:/ruta/a/youtube-transcripts", "run", "yt-transcripts-mcp"],
    "env": { "YT_TRANSCRIPTS_DIR": "C:/ruta/a/datos", "YT_LANGS": "original" }
  }
}
```

## Herramientas MCP

| Herramienta | Uso |
|---|---|
| `search_youtube(query, kind=video\|channel\|playlist, limit=10, sort=relevance\|date\|views\|rating, upload_date=hour\|today\|week\|month\|year, duration=short\|medium\|long)` | **Busca en todo YouTube**, en vivo. Videos: titulo, enlace, canal (@handle, ID), duracion, vistas, descripcion. Canales: ID, @handle, suscriptores, descripcion. Marca lo que ya esta en cache |
| `find_topic_candidates(channel, terms, max_per_term=30, use_youtube_search=True)` | **Descubrimiento por tema**: busca varios terminos por tres vias (buscador del canal en YouTube, titulo/descripcion local, lo hablado ya descargado) y devuelve candidatos con `sources` para que el modelo elija |
| `search_channel_videos(channel, query, limit=20)` | Buscador propio del canal en YouTube: titulos y descripciones de **todo** el canal sin haberlo descargado |
| `harvest_channel(channel, max_videos=20, title_filter, video_ids, list_limit, languages, metadata=True, tab, retry_errors, delay_seconds)` | Lista el canal y procesa hasta `max_videos` videos pendientes: metadatos + transcripcion. `title_filter`/`video_ids` limitan cuales. Si `pending > 0`, volver a llamarla |
| `harvest_channel(channel, max_videos=0)` | Solo lista el canal (titulos de todos los videos) sin bajar nada mas |
| `fetch_metadata(channel, max_videos=50, title_filter, video_ids)` | Solo descripcion, capitulos, tags y fecha exacta (sin transcribir), para filtrar por descripcion antes de decidir |
| `find_videos(channel, title, description, text, date_from, date_to, min_minutes, max_minutes, has_transcript, video_ids, sort, limit, offset)` | **Filtra** videos: titulo, enlace, fecha, duracion, estado y fragmento de la descripcion |
| `search_transcripts(query, channel, title, description, date_from, date_to, video_ids, max_results, per_video)` | Busca en lo hablado por relevancia; enlace `&t=` al segundo, capitulo y fragmento resaltado |
| `get_transcript(video, format=paragraphs\|text\|segments, clean, max_chars=20000, offset)` | Texto paginado (`next_offset`). Si el video no esta en cache, lo baja |
| `get_video_info(video)` | Descripcion completa, capitulos, tags, fecha exacta, vistas y estado de la transcripcion |
| `list_channels()` | Canales en cache: videos listados, con metadatos y con transcripcion |
| `export_videos(video_ids, channel, title, description, text, query, date_from, date_to, language, limit=None, format=md\|pdf\|both, doc_title, include_description, include_chapters, max_chars_per_file=400000, return_content, fetch_missing=false, fetch_limit=50)` | **Documento final** con TODOS los videos que cumplen el filtro: indice, metadatos, descripcion, capitulos y transcripcion con `[m:ss]`. Con `fetch_missing` descarga antes lo que falta. Devuelve rutas, tokens y `coverage` |
| `export_channel(channel, format=jsonl\|csv\|md, text_format, title_filter)` | Archivo con titulo, enlace, fecha, idioma, descripcion y transcripcion |
| `rebuild_index()` | Reconstruye el indice desde los JSON |

Tambien expone el recurso `yt://video/{video_id}` (transcripcion en Markdown con
descripcion), `yt://exports/{nombre}.md` (documentos generados), `yt://channels`, y los prompts
`dump_tema_canal(canal, tema, formato=pdf)`, `investigar_tema(channel, tema)` y `resumir_video(video)`.

`channel` acepta `@handle`, `handle`, ID `UC...`, URL del canal o URL de playlist. En las
herramientas de lectura tambien vale el nombre del canal.

### Sintaxis de filtros (`title`, `description`, `text`, `query`, `title_filter`)

| Escribes | Encuentra |
|---|---|
| `inflacion precios` | ambas palabras, en cualquier orden (sin importar tildes/mayusculas) |
| `"tasa de interes"` | la frase exacta |
| `invers*` | prefijo: inversion, inversiones, inversor... |
| `bitcoin OR ethereum` | cualquiera de las dos |
| `precios -salarios` o `precios NOT salarios` | excluye |

La descripcion solo se puede filtrar en videos con metadatos (`harvest_channel` con
`metadata=true`, que es el defecto, o `fetch_metadata`). El titulo esta disponible para
todos los videos listados.

### Dump de un canal sobre un tema -> un solo PDF

Pide algo como *"dame en un PDF todo lo que QuantumFracture ha dicho sobre agujeros
negros"* (o usa el prompt `dump_tema_canal`). El modelo:

1. confirma el canal (`search_youtube(kind="channel")` si hace falta),
2. genera de 4 a 10 terminos del tema (sinonimos, conceptos relacionados, siglas),
3. llama `find_topic_candidates`, que junta candidatos de tres vias y dice por cual
   aparecio cada uno (`sources`); los que aparecen por varias vias son los mas seguros,
4. revisa titulo y descripcion y descarta lo que no encaja (aqui entra la intencion),
5. llama `export_videos(video_ids=..., fetch_missing=true, format="pdf", max_chars_per_file=0)`,
6. entrega la ruta del PDF, cuantos videos incluye, cuales faltan y el criterio usado.

El PDF trae indice, un marcador por video y, al final, **"Videos relevantes no
incluidos"** con el motivo de cada uno (sin subtitulos, pendiente porque YouTube limito la
IP, Short/directo fuera del listado...). Si faltan videos por el limite de YouTube, volver a
pedir el mismo dump mas tarde retoma la descarga y genera el PDF completo.

Prueba real (canal de 318 videos, terminos "agujero negro", "agujeros negros", "horizonte de
sucesos", "singularidad", "Hawking"): 60 candidatos, incluidos Shorts que no salen en el
listado principal; los mas fuertes aparecieron por 4-5 vias.

### Documento final para otro LLM (`export_videos`)

Junta los videos elegidos en **un solo archivo**:

- encabezado con fecha, numero de videos, idiomas, criterio de seleccion e instrucciones
  de lectura para el modelo (que significa `[m:ss]`, como enlazar un minuto),
- indice de videos,
- por video: titulo, canal, fecha, duracion, idioma (manual/automatica), enlace, minutos
  donde aparece la busqueda (si se uso `query`), descripcion, capitulos y transcripcion
  en parrafos que empiezan en inicio de frase con `[m:ss]`.

Formatos: **`md`** (recomendado para LLM: menos tokens y estructura clara), **`pdf`** (para
subirlo a una interfaz de chat o leerlo; minutos clicables y un marcador por video) o
`both`. Los archivos van a `<YT_TRANSCRIPTS_DIR>/exports/`.

- **Incluye todos los videos que cumplen el filtro** (`limit=None`). El Markdown se parte en
  archivos de ~100k tokens (`max_chars_per_file=400000`; `0` = un solo archivo) sin cortar
  ningun video. `approx_tokens` estima el tamano (caracteres / 4).
- **`coverage`** dice cuantos videos cumplen el filtro (`matching`), cuantos entraron
  (`with_transcript`), cuantos no tienen transcripcion todavia (`without_transcript`) y, si
  filtraste por descripcion, cuantos **no se pudieron evaluar** por no tener metadatos
  (`not_evaluated_no_metadata`).
- **`fetch_missing=true`** descarga antes (hasta `fetch_limit`, ~5 s por video) los videos que
  cumplen el filtro y no tienen transcripcion; si filtras por descripcion, baja tambien los
  metadatos que falten. Si YouTube limita la IP, genera el documento con lo que haya y lo
  indica en `fetched.blocked` y `hint`. `query` (lo dicho en el video) solo puede buscar en
  transcripciones ya descargadas, asi que no dispara descargas por si sola.

#### Filtro literal vs. intencion del usuario

Los filtros son **por palabras**, no por significado: `inflacion` no encuentra un video
titulado "Por que todo esta mas caro". La intencion la aporta el modelo (las instrucciones
del servidor MCP se lo indican):

1. traducir la peticion a filtros amplios con sinonimos
   (`inflacion OR precios OR "costo de vida" OR caro*`),
2. revisar los candidatos con `find_videos` (titulo + descripcion) o `search_channel_videos`
   y descartar los que no encajan,
3. llamar `export_videos(video_ids=[...])` con los elegidos y explicar el criterio usado.

Ejemplo: *"Dame un documento con todo lo que dijo el canal X sobre inflacion este ano"* ->
`export_videos(channel="@X", query="inflacion", date_from="2026-01-01", format="both")`.

### Flujos tipicos para un modelo

- *"Busca canales de finanzas personales en espanol"*: `search_youtube(query="finanzas personales", kind="channel")`
  -> `harvest_channel` con el `channel_id` elegido.
- *"Videos de esta semana sobre la Fed"*: `search_youtube(query="Reserva Federal", upload_date="week", sort="date")`
  -> `get_transcript` de los que interesen.
- *"Del canal X, los videos sobre neutrinos"*: `search_channel_videos(channel="@X", query="neutrinos")`
  -> `harvest_channel(video_ids=[...])`.
- *"Que dice el canal X sobre inflacion"*: `harvest_channel` -> `search_transcripts(query="inflacion")`
  -> `get_transcript` de los videos relevantes.
- *"Transcribe solo los videos de recetas"*: `fetch_metadata` -> `find_videos(text="receta*")`
  -> `harvest_channel(video_ids=[...])`.
- *"Los tutoriales largos de 2026"*: `find_videos(title="tutorial", date_from="2026-01-01", min_minutes=20)`.

## CLI

```bash
uv run yt-transcripts youtube "QuantumFracture" --kind channel       # buscar canales
uv run yt-transcripts youtube "neutrinos" --sort views --duration medium
uv run yt-transcripts youtube "Reserva Federal" --upload-date week --sort date
uv run yt-transcripts channel-search @QuantumFracture "agujero negro"
uv run yt-transcripts topic @QuantumFracture "agujero negro" "horizonte de sucesos" "Hawking"
uv run yt-transcripts harvest @QuantumFracture --max 50              # 50 videos mas recientes
uv run yt-transcripts harvest @QuantumFracture --all --delay 2       # todo el canal, en tandas
uv run yt-transcripts harvest @QuantumFracture --title "nobel OR neutrino*"
uv run yt-transcripts metadata @QuantumFracture --max 200            # solo descripciones
uv run yt-transcripts find --description "nobel OR telescopio" --from 2026-01-01
uv run yt-transcripts search '"agujero negro" velocidad*' --channel @QuantumFracture
uv run yt-transcripts get "https://www.youtube.com/watch?v=eLpXKTgEEbE" --format paragraphs
uv run yt-transcripts info "https://www.youtube.com/watch?v=-G3cwPHo1Qw"
uv run yt-transcripts doc --channel QuantumFracture --query '"agujero negro" OR neutrino*' --format both
uv run yt-transcripts doc --ids "https://www.youtube.com/watch?v=eLpXKTgEEbE" --format pdf --name chorro
uv run yt-transcripts doc --channel @QuantumFracture --title "neutrino* OR nobel" --fetch-missing --format both
uv run yt-transcripts export @QuantumFracture --format csv --out canal.csv
uv run yt-transcripts reindex
```

`harvest` y `metadata` salen con codigo 2 si YouTube limito la IP. Para IDs que empiezan
por `-`, pasa la URL completa (o `--` antes del ID).

## Configuracion (variables de entorno)

| Variable | Defecto | Efecto |
|---|---|---|
| `YT_TRANSCRIPTS_DIR` | `~/.yt-channel-transcripts` | Carpeta de la cache |
| `YT_LANGS` | `original` | Idiomas preferidos, en orden (`original` = el idioma hablado en el video) |
| `YT_SEARCH_LANG` | `es` | Idioma de la interfaz para `search_youtube` (afecta titulos traducidos) |
| `YT_PDF_FONT` / `YT_PDF_FONT_BOLD` | Arial o DejaVu del sistema | Fuente TTF para el PDF (si no hay ninguna, se usa Helvetica sin caracteres fuera de latin-1) |
| `YT_PROXY_HTTP` / `YT_PROXY_HTTPS` | (vacio) | Proxy para `youtube-transcript-api` si YouTube bloquea la IP |

### Idioma

**Por defecto se baja solo el idioma original** (el que se habla en el video), para que
el modelo lo traduzca despues si hace falta. El original se detecta por la pista
automatica de YouTube (siempre esta en el idioma hablado) y, si no la hay, por el idioma
declarado en los metadatos. Dentro de ese idioma se prefiere la pista manual (mejor
puntuacion) sobre la automatica. Esto evita bajar traducciones automaticas que algunos
canales suben como si fueran pistas manuales.

| `languages` | Resultado |
|---|---|
| `["original"]` (defecto) | idioma hablado en el video |
| `["en"]` | ingles si existe; si no, el original |
| `["en", "es"]` | ingles, si no espanol, si no el original |

El idioma bajado queda guardado por video (`language`, y `is_generated` si era
automatica) y se puede filtrar con `find_videos(language="en")`.

Si un video ya esta guardado en su idioma original y luego pides otro con
`get_transcript(video, languages=["en"])`, se baja esa pista y se guarda **aparte**
(`transcripts_by_lang/<id>.en.json`), sin reemplazar la original. Si ese idioma no
existe, devuelve la guardada con un `note` que lo indica. Las variantes no entran en el
indice de busqueda. `harvest_channel` no vuelve a bajar videos ya procesados aunque
cambies `languages`; usa `get_transcript` para pedir otro idioma de un video concreto.

## Estructura de la cache

```
<YT_TRANSCRIPTS_DIR>/
  UCxxxxxxxx/                 # un directorio por canal (ID estable de YouTube)
    channel.json              # nombre, handle, URL, ultima actualizacion, listado completo si/no
    videos.json               # indice ligero: id, titulo, url, fecha, duracion, estado, idioma, palabras
    meta/<id>.json            # descripcion, capitulos, tags, categorias, fecha exacta
    transcripts/<id>.json     # segmentos {start, duration, text} + idioma y fuente
    transcripts_by_lang/      # <id>.<idioma>.json: otros idiomas pedidos con get_transcript
    export.{jsonl,csv,md}     # exportaciones
  _videos/                    # videos sueltos pedidos con get_transcript/get_video_info
  exports/                    # documentos .md/.pdf generados con export_videos
  index.sqlite                # indice FTS5 derivado (se puede borrar: se rehace solo)
```

Los JSON son la fuente de verdad; `index.sqlite` se reconstruye con `rebuild_index`.

Estados por video: `ok`, `sin_transcripcion` (permanente: desactivada o inexistente),
`error` (transitorio; se reintenta con `retry_errors`), `pendiente`.

## Tests

```bash
uv run pytest -q                              # unitarios + servidor MCP por stdio (sin red)
uv run pytest -q -m network --network      # prueba real contra YouTube
```

## Limitaciones conocidas

- **Bloqueos de YouTube**: con muchas peticiones seguidas YouTube devuelve 429. En las
  pruebas de este proyecto bastaron ~20 transcripciones seguidas desde una IP domestica
  para recibir 429 en ambos metodos (API y subtitulos de yt-dlp), mientras los metadatos
  seguian funcionando. En servidores cloud el bloqueo es casi seguro. La herramienta para, avisa con
  `blocked` y conserva lo bajado; la solucion es esperar, subir `delay` o usar un proxy
  residencial. Usa endpoints no oficiales: un cambio de YouTube puede romper
  `youtube-transcript-api` o `yt-dlp` hasta que publiquen arreglo (`uv lock --upgrade`).
- **Fechas**: exactas para videos con metadatos (`date_exact: true`); los que solo estan
  listados tienen una fecha aproximada (en las pruebas, hasta una semana de desviacion).
- **Metadatos cuestan una peticion por video** (~3 s). Para canales enormes, usa
  `metadata=false` y despues `fetch_metadata` solo donde haga falta.
- `yt-dlp` avisa si no hay `deno`/`node`; se configura para usarlos si existen. No hacen
  falta para metadatos ni subtitulos.
- **Pistas "manuales" que son traducciones automaticas**: con el modo `original` (defecto)
  se evitan, porque se elige la pista del idioma hablado. Si pides un idioma concreto que
  solo existe como una de esas traducciones, se bajara esa.
- **Videos sin pista automatica ni idioma declarado**: el modo `original` no puede
  saber cual es el idioma hablado y toma la primera pista disponible.
- **Videos sin subtitulos** (muchos Shorts, directos recientes, videos con subtitulos
  desactivados) quedan como `sin_transcripcion`; esta herramienta no transcribe audio.
- **PDF**: los emojis de las descripciones se omiten (las fuentes del sistema no los tienen).
  `approx_tokens` es una estimacion; cada modelo tokeniza distinto.
- **Busqueda por palabras** (FTS5 con BM25), no semantica: "coche" no encuentra "automovil".
- **Busqueda en YouTube** (`search_youtube`, `search_channel_videos`): depende del orden y
  la personalizacion de YouTube; los titulos pueden venir traducidos automaticamente segun
  el idioma (`YT_LANGS`, primer idioma). No hay filtro por rango de fechas exacto, solo los
  periodos de la web (hora, hoy, semana, mes, ano).
- Los terminos de servicio de YouTube restringen el acceso automatizado; usalo para
  investigacion o uso personal y con ritmo moderado.
