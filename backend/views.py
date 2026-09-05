from uuid import UUID

from flask_restful import reqparse

from .auth import require_verified_user
from .services import ask_question, create_session, get_all_sessions, get_chat_messages, get_session_by_id, upload_pdf


@require_verified_user
def upload_doc(user, req):
    file = req.files.get("file")
    session_id = req.form.get("session_id")
    if not file:
        return {"error": "PDF file is required"}, 400
    if not session_id:
        return {"error": "session_id is required"}, 400
    try:
        UUID(session_id)
    except ValueError:
        return {"error": "Invalid session_id"}, 400
    if not get_session_by_id(session_id, user.id):
        return {"error": "session not found"}, 404
    try:
        count = upload_pdf(file, session_id, user.id)
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:
        return {"error": f"Failed to process PDF: {exc}"}, 500
    return {"message": "PDF processed successfully", "session_id": session_id, "chunks": count}, 201


@require_verified_user
def new_chat(user, req):
    chat_id, session_id = create_session(user.id)
    return {"chat_id": chat_id, "session_id": session_id}, 201


@require_verified_user
def list_sessions(user, req):
    return get_all_sessions(user.id), 200


@require_verified_user
def retrieve_previous_session(user, req):
    parser = reqparse.RequestParser()
    parser.add_argument("session_id", type=str, required=True, location="args", help="session_id is required")
    session_id = parser.parse_args()["session_id"]
    try:
        UUID(session_id)
    except ValueError:
        return {"error": "Invalid session_id"}, 400
    session = get_session_by_id(session_id, user.id)
    if not session:
        return {"error": "session not found"}, 404
    return {**session, "messages": get_chat_messages(session_id, user.id)}, 200


@require_verified_user
def get_response(user, req):
    data = req.get_json(silent=True) or {}
    session_id = data.get("session_id")
    question = data.get("question")
    if not session_id or not question:
        return {"error": "session_id and question are required"}, 400
    try:
        UUID(session_id)
    except ValueError:
        return {"error": "Invalid session_id"}, 400
    question = question.strip()
    if not question:
        return {"error": "Question cannot be empty"}, 400
    if not get_session_by_id(session_id, user.id):
        return {"error": "session not found"}, 404
    try:
        answer = ask_question(question, session_id, user.id)
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except Exception as exc:
        return {"error": f"Failed to generate response: {exc}"}, 500
    return {"answer": answer}, 200
