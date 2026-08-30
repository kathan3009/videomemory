import { VerifyEmailForm } from '../components/AccountRecovery';
import { Brand } from '../components/Mark';

export default function VerifyEmailPage() {
  return <main className="auth-shell"><div className="noise" aria-hidden="true" /><nav className="auth-nav"><Brand /><a href="/login">Sign in</a></nav><div className="auth-grid"><VerifyEmailForm /><div className="auth-art" aria-hidden="true"><div className="auth-orbit auth-orbit-a" /><div className="auth-orbit auth-orbit-b" /><div className="auth-time">TRUE</div><span>ADDRESS VERIFIED</span></div></div></main>;
}
