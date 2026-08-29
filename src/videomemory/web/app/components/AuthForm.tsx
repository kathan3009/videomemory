'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '../lib/api';

type AuthResponse = {
  user: { name: string; email: string };
  api_key?: string;
};

export function AuthForm({ mode }: { mode: 'login' | 'signup' }) {
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [createdKey, setCreatedKey] = useState('');
  const [copied, setCopied] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const payload = await api<AuthResponse>(`/api/auth/${mode}`, {
        method: 'POST',
        body: JSON.stringify({ name, email, password }),
      });
      if (mode === 'signup' && payload.api_key) {
        setCreatedKey(payload.api_key);
      } else {
        router.push('/dashboard');
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not continue');
    } finally {
      setBusy(false);
    }
  }

  async function copyKey() {
    await navigator.clipboard.writeText(createdKey);
    setCopied(true);
  }

  if (createdKey) {
    return (
      <div className="key-reveal">
        <div className="key-success"><span className="status-dot" /> Account ready</div>
        <h1>Save your first<br />MCP key.</h1>
        <p>This secret is shown once. Keep it in your password manager; you can rotate it from the dashboard.</p>
        <div className="secret-field"><code>{createdKey}</code><button type="button" onClick={copyKey}>{copied ? 'Copied' : 'Copy'}</button></div>
        <button className="button button-primary auth-submit" type="button" onClick={() => router.push('/dashboard')}>
          Open dashboard <span>↗</span>
        </button>
      </div>
    );
  }

  return (
    <form className="auth-form" onSubmit={submit}>
      <div className="auth-heading">
        <p className="section-kicker">{mode === 'signup' ? 'CREATE YOUR MEMORY' : 'WELCOME BACK'}</p>
        <h1>{mode === 'signup' ? <>Start with<br />five videos.</> : <>Return to<br />your library.</>}</h1>
        <p>{mode === 'signup' ? 'No card required. Your first private MCP key is created with your account.' : 'Sign in to manage videos, usage, billing, and agent connections.'}</p>
      </div>
      {mode === 'signup' && (
        <label>
          <span>Name</span>
          <input name="name" autoComplete="name" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="Kathan Desai" />
        </label>
      )}
      <label>
        <span>Email</span>
        <input name="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" />
      </label>
      <label>
        <span>Password</span>
        <input name="password" type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} required minLength={10} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="10+ characters" />
      </label>
      {error && <div className="form-error" role="alert">{error}</div>}
      <button className="button button-primary auth-submit" type="submit" disabled={busy}>
        {busy ? 'Working…' : mode === 'signup' ? 'Create free account' : 'Sign in'} <span>↗</span>
      </button>
      <p className="auth-switch">
        {mode === 'signup' ? 'Already have an account?' : 'New to Videomemory?'}{' '}
        <a href={mode === 'signup' ? '/login' : '/signup'}>{mode === 'signup' ? 'Sign in' : 'Start free'}</a>
      </p>
    </form>
  );
}
