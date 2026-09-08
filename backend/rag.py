import os
import tempfile
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.tools import create_retriever_tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from google import genai
from google.genai import types
from langchain_core.embeddings import Embeddings


BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"
COLLECTION_NAME = "pdf_documents"


class GeminiEmbeddings(Embeddings):

    def __init__(self):
        self.client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY")
        )
        self.model = "gemini-embedding-001"

    def embed_documents(self, texts):
        if not texts:
            return []

        result = self.client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT"
            )
        )

        return [embedding.values for embedding in result.embeddings]

    def embed_query(self, text):
        if not text or not text.strip():
            raise ValueError("Cannot create an embedding for an empty query.")

        result = self.client.models.embed_content(
            model=self.model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY"
            )
        )

        return result.embeddings[0].values


embeddings = GeminiEmbeddings()

vector_store = Chroma(
    collection_name=COLLECTION_NAME,
    embedding_function=embeddings,
    persist_directory=str(CHROMA_DIR)
)

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200
)


def ingest_pdf(file_storage, session_id: str, user_id: int) -> int:

    if Path(file_storage.filename or "").suffix.lower() != ".pdf":
        raise ValueError("Only PDF files are supported.")

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pdf"
        ) as tmp:
            temp_path = tmp.name
            file_storage.save(temp_path)

        docs = PyPDFLoader(temp_path).load()

        for doc in docs:
            doc.metadata["session_id"] = session_id
            doc.metadata["user_id"] = str(user_id)

        chunks = splitter.split_documents(docs)

        # Remove empty chunks before sending them to Gemini
        chunks = [
            chunk
            for chunk in chunks
            if chunk.page_content and chunk.page_content.strip()
        ]

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
           batch_size = 20

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            vector_store.add_documents(batch)

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

    return create_retriever_tool(
        retriever,
        name="pdf_search",
        description=(
            "Search the PDF uploaded for this chat session. "
            "You MUST provide a meaningful, non-empty search query. "
            "Never call this tool with an empty query. "
            "For questions like 'what is this PDF about?', "
            "search using a meaningful query such as 'document title, "
            "main topic, purpose, overview, and key information'. "
            "Use this tool for information contained in the PDF."
        )
    )
def delete_pdf_data(session_id: str, user_id: int):
    vector_store.delete(
        where={
            "$and": [
                {"session_id": {"$eq": session_id}},
                {"user_id": {"$eq": str(user_id)}}
            ]
        }
    )   