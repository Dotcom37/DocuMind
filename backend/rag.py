import os
import tempfile
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.tools import create_retriever_tool
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"
COLLECTION_NAME = "pdf_documents"

embeddings = OllamaEmbeddings(model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
vector_store = Chroma(collection_name=COLLECTION_NAME, embedding_function=embeddings, persist_directory=str(CHROMA_DIR))
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)


def ingest_pdf(file_storage, session_id: str, user_id: int) -> int:
    if Path(file_storage.filename or "").suffix.lower() != ".pdf": 
        raise ValueError("Only PDF files are supported.")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            temp_path = tmp.name
            file_storage.save(temp_path)
        docs = PyPDFLoader(temp_path).load()
        for doc in docs:
            doc.metadata["session_id"] = session_id
            doc.metadata["user_id"] = str(user_id)
        chunks = splitter.split_documents(docs)
        try:
            vector_store.delete(
            where={
                "$and": [
                    {"session_id": {"$eq": session_id}},
                    {"user_id": {"$eq": str(user_id)}}
                ]
            }
             )
        except Exception:
            pass
        if chunks:
            vector_store.add_documents(chunks)
        return len(chunks)
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def get_pdf_search_tool(session_id: str, user_id: int):
    retriever = vector_store.as_retriever(
    search_kwargs={
        "k": 3,
        "filter": {
            "$and": [
                {"session_id": {"$eq": session_id}},
                {"user_id": {"$eq": str(user_id)}}
                ]
            }
        }
    )
    return create_retriever_tool(retriever, name="pdf_search", description="Search the PDF uploaded for this chat session. Use this for characters, events, places, facts, names, and story details.")
