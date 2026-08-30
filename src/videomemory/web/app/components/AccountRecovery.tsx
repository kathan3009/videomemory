'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { captchaEnabled, Turnstile } from './Turnstile';

type VerifyResponse = { api_key: string; user: { email: string } };

export function ForgotPasswordForm() {
  const [email, setEmail] = useState('');
  const [captchaToken, setCaptchaToken] = useState('');
  const [resetSignal, setResetSignal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (captchaEnabled && !captchaToken) return setError('Complete the security check to continue.');
    setBusy(true); setError('');
    try {
      const result = await api<{ message: string }>('/api/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email, captcha_token: captchaToken }) });
      setMessage(result.message);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not send the reset link');
      setCaptchaToken(''); setResetSignal((value) => value + 1);
    } finally { setBusy(false); }
  }

  if (message) return <div className="key-reveal"><div className="key-success"><span className="status-dot" /> Request received</div><h1>Check your<br />inbox.</h1><p>{message}</p><a className="button button-primary auth-submit" href="/login">Return to sign in <span>↗</span></a></div>;
  return <form className="auth-form" onSubmit={submit}><div className="auth-heading"><p className="section-kicker">ACCOUNT RECOVERY</p><h1>Reset your<br />password.</h1><p>Enter your account email. We will send a one-time link that expires in 30 minutes.</p></div><label><span>Email</span><input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" /></label><Turnstile action="recover" onToken={setCaptchaToken} resetSignal={resetSignal} />{error && <div className="form-error" role="alert">{error}</div>}<button className="button button-primary auth-submit" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'} <span>↗</span></button><p className="auth-switch"><a href="/login">Back to sign in</a></p></form>;
}

export function ResetPasswordForm() {
  const tokenRef = useRef('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    tokenRef.current = new URLSearchParams(window.location.search).get('token') || '';
    window.history.replaceState({}, '', window.location.pathname);
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    const token = tokenRef.current;
    if (!token) return setError('This reset link is missing its token.');
    if (password !== confirm) return setError('Passwords do not match.');
    setBusy(true);
    try { await api('/api/auth/reset-password', { method: 'POST', body: JSON.stringify({ token, password }) }); setDone(true); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not reset the password'); }
    finally { setBusy(false); }
  }
  if (done) return <div className="key-reveal"><div className="key-success"><span className="status-dot" /> Password updated</div><h1>You are<br />secure again.</h1><p>Every browser session and MCP key was revoked. Sign in and create a fresh agent key when you are ready.</p><a className="button button-primary auth-submit" href="/login">Sign in <span>↗</span></a></div>;
  return <form className="auth-form" onSubmit={submit}><div className="auth-heading"><p className="section-kicker">NEW CREDENTIAL</p><h1>Choose a new<br />password.</h1><p>Use at least 10 characters. Completing this reset signs out every session and revokes existing MCP keys.</p></div><label><span>New password</span><input type="password" autoComplete="new-password" minLength={10} maxLength={256} required value={password} onChange={(event) => setPassword(event.target.value)} /></label><label><span>Confirm password</span><input type="password" autoComplete="new-password" minLength={10} maxLength={256} required value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>{error && <div className="form-error" role="alert">{error}</div>}<button className="button button-primary auth-submit" disabled={busy}>{busy ? 'Updating…' : 'Update password'} <span>↗</span></button></form>;
}

export function VerifyEmailForm() {
  const [status, setStatus] = useState('Verifying your email…');
  const [key, setKey] = useState('');
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get('token') || '';
    window.history.replaceState({}, '', window.location.pathname);
    if (!token) {
      const timer = window.setTimeout(() => setStatus('This verification link is missing its token.'), 0);
      return () => window.clearTimeout(timer);
    }
    api<VerifyResponse>('/api/auth/verify-email', { method: 'POST', body: JSON.stringify({ token }) })
      .then((result) => { setKey(result.api_key); setStatus('Email verified'); })
      .catch((caught) => setStatus(caught instanceof Error ? caught.message : 'Verification failed'));
  }, []);
  async function copy() { await navigator.clipboard.writeText(key); setCopied(true); }
  return <div className="key-reveal"><div className="key-success"><span className="status-dot" /> {status}</div><h1>{key ? <>Save your first<br />MCP key.</> : <>Activating your<br />memory.</>}</h1><p>{key ? 'Your address is verified. This secret is shown once; store it in your password manager.' : 'The activation link is being checked securely.'}</p>{key && <><div className="secret-field"><code>{key}</code><button type="button" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button></div><a className="button button-primary auth-submit" href="/dashboard">Open dashboard <span>↗</span></a></>}</div>;
}
