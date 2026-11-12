# youtube-transcripts

Servidor MCP y CLI para obtener **titulo, enlace y transcripcion** de los videos de
un canal de YouTube, guardarlos en una cache local y buscarlos o exportarlos.

## Por que existe (y que NO reinventa)

Antes de escribirlo se revisaron los proyectos open source existentes (noviembre 2026):

| Proyecto | Que hace | Por que no basta solo |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Lista los videos de un canal y sus metadatos | No es MCP; no gestiona transcripciones como texto |
| [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | Baja la transcripcion de un video, sin API key | Un video a la vez; sin nocion de canal ni cache |
| [yt-mcp-server](https://github.com/PodevynLoris/youtube-mcp-server) | MCP con `get_channel_videos`, `get_transcript`, busqueda en canal | Segun su README: sin cache local ni exportacion; cada transcripcion completa se pide a YouTube y entra al contexto del modelo |
| [YTScribe](https://github.com/dparedesi/YTScribe) | CLI que archiva canales a Markdown | No es MCP; resume con APIs de pago |
| [yt-dlp-transcripts](https://pypi.org/project/yt-dlp-transcripts/) | Canal -> CSV | No es MCP; sin reanudacion |

Decision: **reutilizar** `yt-dlp` (listado) y `youtube-transcript-api` (transcripciones),
que son las piezas maduras, y escribir solo la capa fina que faltaba:

- cache en disco **incremental y reanudable** (no se pide dos veces lo ya bajado; un corte
  o un bloqueo de IP no pierde nada),
- herramientas MCP que devuelven **resumenes** y paginan el texto, para no llenar el
  contexto del modelo con miles de palabras que no pidio,
- busqueda sin tildes con enlace al segundo exacto, y exportacion a jsonl/csv/md.

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
    "env": { "YT_TRANSCRIPTS_DIR": "C:/ruta/a/datos", "YT_LANGS": "es,en" }
  }
}
```

## Herramientas MCP

| Herramienta | Uso |
|---|---|
| `harvest_channel(channel, max_videos=25, list_limit=None, languages, tab, retry_errors, delay_seconds)` | Lista el canal y baja hasta `max_videos` transcripciones pendientes. Devuelve un resumen; si `pending > 0`, volver a llamarla |
| `list_channels()` | Canales en cache y cuantas transcripciones tiene cada uno |
| `list_videos(channel, only_with_transcript, limit, offset)` | Titulo, enlace, fecha, duracion, estado, idioma, palabras |
| `get_transcript(video, timestamps, max_chars=20000, offset)` | Texto completo paginado (`next_offset`). Si el video no esta en cache, lo baja |
| `search_transcripts(query, channel, max_results, context_chars)` | Busca una frase sin importar tildes; devuelve enlace `&t=` al segundo |
| `export_channel(channel, format=jsonl\|csv\|md, timestamps)` | Escribe titulo+enlace+fecha+idioma+transcripcion de todo el canal y devuelve la ruta |

`channel` acepta `@handle`, `handle`, ID `UC...`, URL del canal o URL de playlist. En las
herramientas de lectura tambien vale el nombre del canal.

## CLI

```bash
uv run yt-transcripts harvest @QuantumFracture --max 50          # 50 transcripciones mas recientes
uv run yt-transcripts harvest @QuantumFracture --all --delay 2   # todo el canal, en tandas
uv run yt-transcripts list QuantumFracture --only-ok
uv run yt-transcripts get https://www.youtube.com/watch?v=eLpXKTgEEbE --timestamps
uv run yt-transcripts search "agujero negro" --channel @QuantumFracture
uv run yt-transcripts export @QuantumFracture --format csv --out canal.csv
```

`harvest` sale con codigo 2 si YouTube bloqueo la IP.

## Configuracion (variables de entorno)

| Variable | Defecto | Efecto |
|---|---|---|
| `YT_TRANSCRIPTS_DIR` | `~/.yt-channel-transcripts` | Carpeta de la cache |
| `YT_LANGS` | `es,en` | Idiomas preferidos, en orden |
| `YT_PROXY_HTTP` / `YT_PROXY_HTTPS` | (vacio) | Proxy para `youtube-transcript-api` si YouTube bloquea la IP |

Seleccion de idioma: pista **manual** en el primer idioma pedido que exista; si no,
**automatica** en un idioma pedido; si no, la automatica del idioma original del video;
si no, cualquier manual. El idioma y si era automatica quedan guardados por video.

## Estructura de la cache

```
<YT_TRANSCRIPTS_DIR>/
  UCxxxxxxxx/                 # un directorio por canal (ID estable de YouTube)
    channel.json              # nombre, handle, URL, ultima actualizacion
    videos.json               # indice: id, titulo, url, fecha, duracion, estado, idioma, palabras
    transcripts/<id>.json     # segmentos {start, duration, text}
    export.{jsonl,csv,md}     # exportaciones
  _videos/transcripts/        # videos sueltos pedidos con get_transcript
```

Estados por video: `ok`, `sin_transcripcion` (permanente: desactivada o inexistente),
`error` (transitorio; se reintenta con `retry_errors`), `pendiente`.

## Tests

```bash
uv run pytest -q                              # unitarios + servidor MCP por stdio (sin red)
uv run pytest -q -m network --network      # prueba real contra YouTube
```

## Limitaciones conocidas

- **Bloqueos de YouTube**: con muchas peticiones seguidas YouTube puede devolver 429 o
  bloquear la IP (en servidores cloud es casi seguro). La herramienta para, avisa con
  `blocked` y conserva lo bajado; la solucion es esperar, subir `delay` o usar un proxy
  residencial. Usa endpoints no oficiales: un cambio de YouTube puede romper
  `youtube-transcript-api` o `yt-dlp` hasta que publiquen arreglo (`uv lock --upgrade`).
- **Fechas aproximadas**: en el listado rapido YouTube da fechas relativas ("hace 2 semanas");
  la fecha guardada es aproximada y la desviacion crece con la antiguedad del video.
- **Pistas "manuales" que son traducciones automaticas**: algunos canales suben subtitulos
  traducidos por IA como pista manual; no se pueden distinguir. Si quieres el idioma
  original, pide `languages=["en"]` (o el que sea).
- **Videos sin subtitulos** (muchos Shorts, directos recientes, videos con subtitulos
  desactivados) quedan como `sin_transcripcion`; esta herramienta no transcribe audio.
- **Busqueda literal**, no semantica.
- Los terminos de servicio de YouTube restringen el acceso automatizado; usalo para
  investigacion o uso personal y con ritmo moderado.
