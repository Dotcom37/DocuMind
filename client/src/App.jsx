import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import './App.css'

const API = import.meta.env.VITE_API_URL || "http://localhost:8000"

function csrfToken() {
  return document.cookie.split('; ').find(row => row.startsWith('csrf_token='))?.split('=')[1] || ''
}

async function api(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const headers = { ...(options.headers || {}) }
  if (method !== 'GET' && method !== 'HEAD') headers['X-CSRF-TOKEN'] = csrfToken()
  const res = await fetch(`${API}${path}`, { ...options, headers, credentials: 'include' })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.error || 'Request failed')
    Object.assign(err, data)
    throw err
  }
  return data
}

function Auth({ onLogin }) {
  const [mode, setMode] = useState('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [needsOtp, setNeedsOtp] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      if (needsOtp) {
        const data = await api('/auth/verify-otp', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ email, otp }) })
        onLogin(data.user)
        return
      }
      const path = mode === 'login' ? '/auth/login' : '/auth/register'
      const body = mode === 'login' ? { email, password } : { name, email, password }
      const data = await api(path, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
      if (mode === 'register') {
        setNeedsOtp(true)
      } else {
        onLogin(data.user)
      }
    } catch (e) {
      if (e.requires_verification) setNeedsOtp(true)
      setError(e.message)
    } finally { setLoading(false) }
  }

  async function resend() {
    setError('')
    try { await api('/auth/resend-otp', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ email }) }); setError('A new OTP was sent.') }
    catch (e) { setError(e.message) }
  }

  return <div className="auth-page">
    <div className="auth-card">
      <div className="brand auth-brand"><div className="brand-mark">R</div><div><strong>RAG Chat</strong><span>PDF intelligence</span></div></div>
      <h1>{needsOtp ? 'Verify your email' : mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
      <p className="auth-subtitle">{needsOtp ? `Enter the 6-digit code sent to ${email}.` : 'Sign in to keep your chats and documents private.'}</p>
      {error && <div className="error">{error}</div>}
      <form onSubmit={submit}>
        {!needsOtp && mode === 'register' && <input value={name} onChange={e => setName(e.target.value)} placeholder="Full name" required />}
        {!needsOtp && <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Email" required />}
        {!needsOtp && <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Password (8+ characters)" minLength="8" required />}
        {needsOtp && <input inputMode="numeric" pattern="[0-9]{6}" maxLength="6" value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, ''))} placeholder="6-digit OTP" required />}
        <button className="auth-submit" disabled={loading}>{loading ? 'Please wait…' : needsOtp ? 'Verify & continue' : mode === 'login' ? 'Log in' : 'Create account'}</button>
      </form>
      {needsOtp && <button className="link-button" onClick={resend}>Resend OTP</button>}
      {!needsOtp && <>
        <div className="divider"><span>or</span></div>
        <a className="google-button" href={`${API}/auth/google`}>Continue with Google</a>
        <p className="switch">{mode === 'login' ? 'New here?' : 'Already have an account?'} <button onClick={() => {setMode(mode === 'login' ? 'register' : 'login'); setError('')}}>{mode === 'login' ? 'Create account' : 'Log in'}</button></p>
      </>}
    </div>
  </div>
}

function ChatApp({ user, onLogout }) {
  const [sessions, setSessions] = useState([])
  const [session, setSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  useEffect(() => { loadSessions() }, [])
  async function loadSessions() { try { setSessions(await api('/sessions')) } catch (e) { setError(e.message) } }
  async function createChat() { setError(''); try { const data = await api('/chat', { method: 'POST' }); setSession(data); setMessages([]); await loadSessions() } catch (e) { setError(e.message) } }
  async function openChat(s) { setError(''); try { const data = await api(`/chat/session?session_id=${encodeURIComponent(s.session_id)}`); setSession(data); setMessages(data.messages || []) } catch (e) { setError(e.message) } }
  async function deleteChat(sessionId) {setError('')

  try {
    await api(`/chat/${sessionId}`, {
      method: 'DELETE'
    })

    // Remove it from the sidebar
    setSessions(prev =>
      prev.filter(s => s.session_id !== sessionId)
    )

    // If the deleted chat was currently open, clear it
    if (session?.session_id === sessionId) {
      setSession(null)
      setMessages([])
    }
  } catch (e) {
    setError(e.message)
  }
}
  async function uploadPdf() {
    if (!file || !session) return; setUploading(true); setError('')
    try { const form = new FormData(); form.append('file', file); form.append('session_id', session.session_id); await api('/upload', { method: 'POST', body: form }); setFile(null); if (inputRef.current) inputRef.current.value = '' }
    catch (e) { setError(e.message) } finally { setUploading(false) }
  }
  async function sendMessage(e) {
    e?.preventDefault(); const text = question.trim(); if (!text || !session || loading) return
    setQuestion(''); setError(''); setMessages(prev => [...prev, { type: 'human', content: text }]); setLoading(true)
    try { const data = await api('/chat/response', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ session_id: session.session_id, question: text }) }); setMessages(prev => [...prev, { type: 'ai', content: data.answer }]); await loadSessions() }
    catch (e) { setMessages(prev => prev.slice(0, -1)); setError(e.message) } finally { setLoading(false) }
  }
  async function logout() { await api('/auth/logout', { method: 'POST' }).catch(() => {}); onLogout() }

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">R</div><div><strong>RAG Chat</strong><span>PDF intelligence</span></div></div>
      <div className="user-box"><div><strong>{user.name}</strong><small>{user.email}</small></div><button onClick={logout}>Log out</button></div>
      <button className="new-chat" onClick={createChat}>＋ New chat</button>
      <div className="history-title">Recent chats</div>
      <div className="history">{sessions.length === 0 && <div className="empty-history">No chats yet</div>}
      {sessions.map(s => (
  <div className="history-item-wrapper" key={s.session_id}>
    <button
      className={`history-item ${
        session?.session_id === s.session_id ? 'active' : ''
      }`}
      onClick={() => openChat(s)}
    >
      <span>{s.title || `chat_${s.chat_id}`}</span>
      <small>{new Date(s.updated_at).toLocaleDateString()}</small>
    </button>

    <button
      className="delete-chat"
      onClick={(e) => {
        e.stopPropagation()
        deleteChat(s.session_id)
      }}
      title="Delete chat"
    >
      🗑️
    </button>
  </div>
))}
    </div>
    </aside>
    <main className="main">
      <header><div><h1>{session ? (session.title || `Chat ${session.chat_id}`) : 'PDF Research Assistant'}</h1><p>{session ? 'Ask questions about your uploaded document.' : 'Create a chat and upload a PDF to begin.'}</p></div></header>
      {!session ? <section className="welcome"><div className="welcome-icon">✦</div><h2>Chat with your PDF</h2><p>Upload a document, then ask questions. Your chats and documents are tied to your account.</p><button onClick={createChat}>Start a new chat</button></section> : <>
        <section className="messages">{messages.length === 0 && <div className="starter"><h2>Your document, your questions.</h2><p>Upload a PDF below, then try asking something like “Who is Adam in the story?”</p></div>}{messages.map((m, i) => <div className={`message ${m.type === 'human' ? 'user' : 'assistant'}`} key={i}><div className="avatar">{m.type === 'human' ? 'You' : 'AI'}</div><div className="bubble"><ReactMarkdown>{m.content}</ReactMarkdown></div></div>)}{loading && <div className="message assistant"><div className="avatar">AI</div><div className="bubble typing">Thinking<span>.</span><span>.</span><span>.</span></div></div>}</section>
        {error && <div className="error">{error}</div>}
        <section className="composer-wrap"><div className="upload-row"><label className="file-picker"><input ref={inputRef} type="file" accept="application/pdf" onChange={e => setFile(e.target.files?.[0] || null)} /><span>📎 {file ? file.name : 'Choose PDF'}</span></label><button className="upload" disabled={!file || uploading} onClick={uploadPdf}>{uploading ? 'Processing…' : 'Upload PDF'}</button></div><form className="composer" onSubmit={sendMessage}><input value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask anything about your PDF…" /><button disabled={!question.trim() || loading}>Send</button></form></section>
      </>}
    </main>
  </div>
}

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)
  useEffect(() => { api('/auth/me').then(data => setUser(data.user)).catch(() => {}).finally(() => setChecking(false)) }, [])
  if (checking) return <div className="auth-loading">Loading…</div>
  return user ? <ChatApp user={user} onLogout={() => setUser(null)} /> : <Auth onLogin={setUser} />
}
