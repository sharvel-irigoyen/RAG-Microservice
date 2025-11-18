# RAG Microservice

<!-- UI friendly header with quick facts -->
`FastAPI` • `OpenAI Embeddings` • `Pinecone` • `Document Extraction`

Microservicio listo para production que conecta archivos PDF/DOCX/TXT con un flujo de Retrieval-Augmented Generation (RAG). Expone endpoints REST para extraer texto, generar embeddings con OpenAI y sincronizar resultados en Pinecone para búsquedas semánticas ultra rápidas.

> **Objetivo:** centralizar ingestión y consulta de documentos en un servicio simple, seguro y extensible.

---

## Tabla de contenidos
1. [Arquitectura](#arquitectura)
2. [Características clave](#características-clave)
3. [Variables de entorno](#variables-de-entorno)
4. [Instalación y despliegue](#instalación-y-despliegue)
5. [Flujo de trabajo recomendado](#flujo-de-trabajo-recomendado)
6. [Endpoints disponibles](#endpoints-disponibles)
7. [Notas y buenas prácticas](#notas-y-buenas-prácticas)

---

## Arquitectura

| Módulo | Rol |
| --- | --- |
| **FastAPI** (`app.py`) | Orquesta la API REST, maneja CORS y valida payloads con Pydantic. |
| **OpenAI API** | Genera embeddings (`text-embedding-3-small`) con dimensión configurable (`EMBED_DIM`). |
| **Pinecone** | Almacena y consulta vectores; soporta namespaces para aislar colecciones. |
| **Extractores** | Usa `pypdf`, `python-docx` o decodificación de texto plano para normalizar documentos. |

---

## Características clave

- **Extracción inteligente** de PDFs, Word y TXT con limpieza básica de texto.
- **Embeddings parametrizables**: cambia dimensión o modelo con variables de entorno.
- **CRUD vectorial**: upsert, delete y query contra Pinecone usando filtros por metadata.
- **Health check** con datos de configuración para debugging rápido.
- **Seguridad**: separación de namespaces, dependencia mínima de servicios externos.
- **Docker-ready**: incluye `Dockerfile` y `docker-compose.yml` para levantar el stack en un solo comando.

---

## Variables de entorno

Configura un archivo `.env` o exporta en tu shell.

| Variable | Obligatoria | Descripción |
| --- | --- | --- |
| `OPENAI_API_KEY` | ✅ | Clave de proyecto en OpenAI. |
| `PINECONE_API_KEY` | ✅ | API key del índice Pinecone. |
| `PINECONE_ENDPOINT` | ✅ | Host del índice (p. ej. `https://xxx.svc.region.pinecone.io`). |
| `PINECONE_INDEX` | ➖ (`rag-main`) | Nombre del índice. |
| `RAG_NAMESPACE` | ➖ (`default`) | Namespace por defecto para operaciones. |
| `EMBED_DIM` | ➖ (`512`) | Dimensión a usar al crear embeddings. Debe coincidir con el índice. |

> 💡 Nunca compartas tus llaves en repos públicos. Usa gestores de secretos o variables de entorno por entorno.

---

## Instalación y despliegue

### Opción A: Docker Compose (recomendada)

1. Completa tu `.env` con llaves reales.
2. Levanta la pila:
   ```bash
   docker compose up --build -d
   ```
3. Verifica desde tu host (puerto publicado en `docker-compose.yml`, por defecto 8100):
   ```bash
   curl http://localhost:8100/health
   ```
4. Logs en vivo:
   ```bash
   docker compose logs -f rag-micro
   ```

> El contenedor se expone en la red bridge `rag_net` y mantiene un healthcheck automático cada 30s.

### Opción B: Local con Python

```bash
git clone <repo> rag-micro
cd rag-micro
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env # o crea uno nuevo con tus llaves
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Verifica:

```bash
curl http://localhost:8000/health
```

### Producción

- Para contenedores, fija `--reload` en `false` (ya está así en el `Dockerfile`) y delega reinicios a Compose/Kubernetes.
- Agrega HTTPS y rate limiting desde tu reverse proxy (Traefik, Nginx).
- Configura variables de entorno en tu orquestador (Docker secrets, ECS task defs, etc.).

---

## Flujo de trabajo recomendado

1. **Upload/Extract**: envía el archivo al endpoint `/extract` para obtener texto limpio.
2. **Embed**: llama a `/embed` con bloques de texto (chunks) para recibir vectores.
3. **Upsert**: publica esos vectores en Pinecone vía `/pinecone/upsert`, adjuntando metadata (p. ej. `document_id`, `page`, `title`).
4. **Query**: consulta `/pinecone/query` enviando texto o un vector ya calculado.
5. **Delete**: elimina documentos completos con `/pinecone/delete_by_document`.

Puedes automatizar el pipeline con workers externos o scripts que consuman estos endpoints.

---

## Endpoints disponibles

| Método & Path | Descripción | Payload mínimo |
| --- | --- | --- |
| `GET /health` | Estado del servicio, índice y namespace por defecto. | – |
| `POST /extract` | Extrae texto de `UploadFile`. Parámetro opcional `mime`. | `file` (multipart) |
| `POST /embed` | Genera embeddings para una lista de textos. | `{ "texts": ["hola", ...] }` |
| `POST /pinecone/upsert` | Inserta vectores con metadata en el namespace elegido. | `{ "namespace": "docs", "points": [{ "id": "...", "values": [...], "metadata": {...} }] }` |
| `POST /pinecone/delete_by_document` | Baja lógica por `document_id` en metadata. | `{ "document_id": "doc-123" }` |
| `POST /pinecone/query` | Busca por similitud. Acepta `text` **o** `vector`. | `{ "text": "¿Qué es X?" }` |

### Ejemplos rápidos

```bash
# Extract
curl -F "file=@ejemplo.pdf" http://localhost:8000/extract

# Embed
curl -X POST http://localhost:8000/embed \
  -H "Content-Type: application/json" \
  -d '{ "texts": ["Capítulo 1...", "Capítulo 2..."] }'

# Query
curl -X POST http://localhost:8000/pinecone/query \
  -H "Content-Type: application/json" \
  -d '{ "text": "política de devoluciones", "topK": 10 }'
```

---

## Notas y buenas prácticas

- **Chunking**: corta documentos largos en fragmentos (p. ej. 200-400 tokens) antes de embebedarlos.
- **Metadata rica**: guarda `document_id`, `source`, `page`, `lang` para filtros efectivos.
- **Observabilidad**: monitorea tiempos de respuesta y errores (FastAPI es compatible con Prometheus/OpenTelemetry).
- **Versionado de modelos**: si cambias `EMBED_DIM` o modelo, crea un índice nuevo para evitar mezclas incompatibles.
- **Pruebas**: incluye scripts o notebooks que ejerciten `/extract` y `/pinecone/query` para validar ingestiones nuevas.

¡Listo! Con este microservicio puedes construir asistentes, buscadores internos o automatizaciones de conocimiento reutilizando la misma base de vectores.
