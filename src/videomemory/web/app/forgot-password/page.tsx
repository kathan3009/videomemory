import { ForgotPasswordForm } from '../components/AccountRecovery';
import { Brand } from '../components/Mark';

export default function ForgotPasswordPage() {
  return <main className="auth-shell"><div className="noise" aria-hidden="true" /><nav className="auth-nav"><Brand /><a href="/login">Sign in</a></nav><div className="auth-grid"><ForgotPasswordForm /><div className="auth-art" aria-hidden="true"><div className="auth-orbit auth-orbit-a" /><div className="auth-orbit auth-orbit-b" /><div className="auth-time">RESET</div><span>ONE-TIME LINK</span></div></div></main>;
}
