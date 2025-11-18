import io
import os
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document as DocxDoc
from fastapi.middleware.cors import CORSMiddleware

from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

# === Config ===
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX   = os.getenv("PINECONE_INDEX", "rag-main")
PINECONE_ENDPOINT = os.getenv("PINECONE_ENDPOINT")
RAG_NAMESPACE    = os.getenv("RAG_NAMESPACE", "default")
EMBED_DIM        = int(os.getenv("EMBED_DIM", "512"))

assert OPENAI_API_KEY,   "OPENAI_API_KEY missing"
assert PINECONE_API_KEY, "PINECONE_API_KEY missing"
assert PINECONE_ENDPOINT, "PINECONE_ENDPOINT missing"

client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX, host=PINECONE_ENDPOINT)

app = FastAPI(title="RAG Microservice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# === Helpers ===
def get_namespace(ns: Optional[str]) -> str:
    """
    Toma un namespace opcional y, si está vacío, usa el RAG_NAMESPACE del .env.
    """
    return (ns or "").strip() or RAG_NAMESPACE

def extract_pdf(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    parts = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        parts.append(txt)
    return "\n".join(parts)

def extract_docx(raw: bytes) -> str:
    f = io.BytesIO(raw)
    doc = DocxDoc(f)
    parts = [p.text for p in doc.paragraphs]
    return "\n".join(parts)

def extract_txt(raw: bytes) -> str:
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return raw.decode("latin-1", errors="ignore")

# === Schemas ===
class EmbedIn(BaseModel):
    texts: List[str]

class UpsertPoint(BaseModel):
    id: str
    values: List[float]
    metadata: Dict[str, Any]

class UpsertIn(BaseModel):
    namespace: Optional[str] = None
    points: List[UpsertPoint]

class DeleteIn(BaseModel):
    namespace: Optional[str] = None
    document_id: str

class QueryIn(BaseModel):
    namespace: Optional[str] = None
    vector: Optional[List[float]] = None
    text: Optional[str] = None
    filter: Optional[Dict[str, Any]] = None
    topK: int = 24
    includeValues: bool = False
    includeMetadata: bool = True

# === Endpoints ===
@app.get("/health")
async def health():
    return {
        "ok": True,
        "index": PINECONE_INDEX,
        "endpoint": PINECONE_ENDPOINT,
        "namespace_default": RAG_NAMESPACE,
        "embed_dim": EMBED_DIM,
    }

@app.post("/extract")
async def extract(file: UploadFile = File(...), mime: Optional[str] = Form(None)):
    raw = await file.read()
    kind = mime or file.content_type or "application/octet-stream"

    if "pdf" in kind:
        text = extract_pdf(raw)
    elif "word" in kind or "msword" in kind or "officedocument" in kind:
        text = extract_docx(raw)
    elif "text" in kind or file.filename.lower().endswith(".txt"):
        text = extract_txt(raw)
    else:
        # heurística simple
        try:
            text = extract_pdf(raw)
        except Exception:
            text = extract_txt(raw)

    text = " ".join(text.split())
    return {"text": text}

@app.post("/embed")
async def embed(body: EmbedIn):
    # Usa modelo + dimensión configurables
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=body.texts,
        dimensions=EMBED_DIM,
    )
    vectors = [d.embedding for d in resp.data]
    return {"vectors": vectors}

@app.post("/pinecone/upsert")
async def pinecone_upsert(body: UpsertIn):
    ns = get_namespace(body.namespace)
    items = [{"id": p.id, "values": p.values, "metadata": p.metadata} for p in body.points]
    index.upsert(vectors=items, namespace=ns)
    return {"ok": True, "namespace": ns, "count": len(items)}

@app.post("/pinecone/delete_by_document")
async def pinecone_delete(body: DeleteIn):
    ns = get_namespace(body.namespace)
    index.delete(namespace=ns, filter={"document_id": {"$eq": body.document_id}})
    return {"ok": True, "namespace": ns}

@app.post("/pinecone/query")
async def pinecone_query(body: QueryIn):
    """
    Endpoint de prueba de búsquedas:
      - Si envías 'text', el micro genera el embedding y consulta.
      - Si envías 'vector', lo usa directamente.
      - Usa namespace del body o el RAG_NAMESPACE por defecto.
    """
    ns = get_namespace(body.namespace)

    if body.vector is None:
        if not body.text:
            return {"ok": False, "error": "Provide 'text' or 'vector'."}
        # embed del texto con la misma dimensión que el índice
        emb = client.embeddings.create(
            model="text-embedding-3-small",
            input=[body.text],
            dimensions=EMBED_DIM,
        ).data[0].embedding
    else:
        emb = body.vector

    payload = {
        "namespace": ns,
        "vector": emb,
        "topK": body.topK,
        "includeValues": body.includeValues,
        "includeMetadata": body.includeMetadata,
    }
    if body.filter:
        payload["filter"] = body.filter

    res = index.query(**payload)
    return {"ok": True, "namespace": ns, **res}
