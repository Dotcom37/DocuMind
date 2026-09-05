# RAG PDF Chat — Flask + React/Vite

This version adds account authentication, email OTP verification, Google OAuth login, and per-user authorization while keeping the existing PDF → embeddings → Chroma → LangGraph flow.

## Authentication flow

### Manual signup
1. `POST /auth/register` with `name`, `email`, and `password`.
2. Flask hashes the password and creates an unverified user.
3. A 6-digit OTP is generated and sent by SMTP.
4. `POST /auth/verify-otp` verifies the code and signs the user in.

### Manual login
`POST /auth/login` checks the password. Unverified accounts receive a new OTP and must verify it first.

### Google login
Open `GET /auth/google`. Google authenticates the user and redirects to `/auth/google/callback`. Flask creates/fetches the user and signs them in.

The backend uses an HttpOnly signed authentication cookie and a separate CSRF cookie for mutating authenticated requests.

## Authorization / user isolation

Every chat session has a `user_id`. Protected endpoints only access sessions belonging to the authenticated user. Chroma metadata contains both `user_id` and `session_id`, and PDF retrieval filters on both values.

A user therefore cannot use another user's session ID to read its chat history or PDF embeddings.

Existing chat sessions/embeddings from before authentication are not assigned to a user. They are left inaccessible to authenticated users; re-upload those PDFs into a new authenticated chat.

## Setup

### Backend

```bash
uv sync
uv run python -m backend.server
```

Create `.env` from `.env.example` and fill in your values.

Make sure Ollama is running:

```bash
ollama pull nomic-embed-text
```

### OTP email

For Gmail SMTP, use an App Password rather than your normal Gmail password. Put it in `SMTP_PASSWORD`.

If SMTP credentials are not configured, development mode prints the OTP in the Flask terminal instead of sending an email.

### Google OAuth

Create a Google OAuth web application and set this authorized redirect URI for local development:

```text
http://127.0.0.1:8000/auth/google/callback
```

Then set:

```text
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

If you change the backend host/port, the redirect URI must match exactly in Google Cloud Console and in the running app.

### Frontend

```bash
cd client
npm install
copy .env.local.example .env.local
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

## API endpoints

### Authentication

- `POST /auth/register` — create account and send OTP
- `POST /auth/verify-otp` — verify OTP and sign in
- `POST /auth/resend-otp` — send a new OTP
- `POST /auth/login` — manual login
- `GET /auth/google` — start Google OAuth
- `GET /auth/google/callback` — Google OAuth callback
- `GET /auth/me` — current authenticated user
- `POST /auth/logout` — clear authentication cookies

### Protected chatbot APIs

- `POST /chat` — create a chat for the authenticated user
- `GET /sessions` — list only that user's chats
- `GET /chat/session?session_id=...` — load only that user's chat
- `POST /upload` — upload a PDF to that user's chat
- `POST /chat/response` — ask a question using that user's PDF retrieval scope

## Security notes

- Passwords are hashed with Werkzeug; plaintext passwords are never stored.
- OTPs are stored as hashes, expire after 10 minutes, and are invalidated after successful use.
- OTP verification is limited to 5 attempts per code.
- Authentication uses an HttpOnly signed cookie.
- Mutating authenticated requests require the CSRF header matching the CSRF cookie.
- Set `COOKIE_SECURE=true` in HTTPS production deployments.
- Use a strong random `JWT_SECRET_KEY` in production.
