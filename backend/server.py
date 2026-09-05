import os

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, session
from flask_cors import CORS
from flask_restful import Api, Resource
from sqlalchemy import inspect, text

from .config.extensions import db
from . import models  # noqa: F401
from .auth import auth_bp
from .views import get_response, list_sessions, new_chat, retrieve_previous_session, upload_doc


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "change-this-in-production")

    db.init_app(app)
    CORS(app, resources={r"/*": {"origins": [os.getenv("FRONTEND_URL", "http://localhost:5173")], "supports_credentials": True}}, expose_headers=["X-CSRF-TOKEN"])
    app.register_blueprint(auth_bp)
    api = Api(app)

    class NewChat(Resource):
        def post(self): return new_chat(request)
    class Sessions(Resource):
        def get(self): return list_sessions(request)
    class PreviousSession(Resource):
        def get(self): return retrieve_previous_session(request)
    class ChatResponse(Resource):
        def post(self): return get_response(request)
    class UploadDocument(Resource):
        def post(self): return upload_doc(request)

    api.add_resource(NewChat, "/chat")
    api.add_resource(Sessions, "/sessions")
    api.add_resource(PreviousSession, "/chat/session")
    api.add_resource(ChatResponse, "/chat/response")
    api.add_resource(UploadDocument, "/upload")

    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)
        columns = {c["name"] for c in inspector.get_columns("chat_sessions")}
        if "user_id" not in columns:
            db.session.execute(text("ALTER TABLE chat_sessions ADD COLUMN user_id INTEGER"))
            db.session.commit()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
