from datetime import datetime
import uuid

from .agent import generate_response
from .config.extensions import db
from .models import ChatSession, Chats
from .rag import ingest_pdf


def create_session(user_id):
    session = ChatSession(session_id=str(uuid.uuid4()), user_id=user_id)
    db.session.add(session)
    db.session.commit()
    return session.chat_id, session.session_id


def _session_for_user(session_id, user_id):
    return ChatSession.query.filter_by(session_id=session_id, user_id=user_id).first()


def get_all_sessions(user_id):
    sessions = ChatSession.query.filter_by(user_id=user_id).order_by(ChatSession.updated_at.desc()).all()
    return [{"chat_id": s.chat_id, "session_id": s.session_id, "title": s.title or f"chat_{s.chat_id}",
             "created_at": s.created_at.isoformat() if s.created_at else None,
             "updated_at": s.updated_at.isoformat() if s.updated_at else None} for s in sessions]


def get_session_by_id(session_id, user_id):
    s = _session_for_user(session_id, user_id)
    if not s:
        return None
    return {"chat_id": s.chat_id, "session_id": s.session_id, "title": s.title or f"chat_{s.chat_id}",
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None}


def get_chat_messages(session_id, user_id):
    if not _session_for_user(session_id, user_id):
        return None
    rows = Chats.query.filter_by(session_id=session_id).order_by(Chats.created_at.asc()).all()
    return [{"type": row.role, "content": row.message} for row in rows]


def save_message(session_id, role, message):
    db.session.add(Chats(session_id=session_id, role=role, message=message))
    db.session.commit()


def touch_session(session_id, title=None):
    session = ChatSession.query.filter_by(session_id=session_id).first()
    if not session:
        return None
    if title and not session.title:
        session.title = title[:100]
    session.updated_at = datetime.utcnow()
    db.session.commit()
    return session


def upload_pdf(file_storage, session_id, user_id):
    if not _session_for_user(session_id, user_id):
        raise PermissionError("You do not have access to this chat")
    return ingest_pdf(file_storage, session_id, user_id)


def ask_question(question, session_id, user_id):
    if not _session_for_user(session_id, user_id):
        raise PermissionError("You do not have access to this chat")
    save_message(session_id, "human", question)
    try:
        response = generate_response(question, session_id, user_id)
        answer = getattr(response, "content", str(response))
        save_message(session_id, "ai", answer)
        touch_session(session_id, question)
        return answer
    except Exception:
        db.session.rollback()
        raise
