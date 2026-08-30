import { ResetPasswordForm } from '../components/AccountRecovery';
import { Brand } from '../components/Mark';

export default function ResetPasswordPage() {
  return <main className="auth-shell"><div className="noise" aria-hidden="true" /><nav className="auth-nav"><Brand /><a href="/login">Sign in</a></nav><div className="auth-grid"><ResetPasswordForm /><div className="auth-art" aria-hidden="true"><div className="auth-orbit auth-orbit-a" /><div className="auth-orbit auth-orbit-b" /><div className="auth-time">NEW</div><span>CREDENTIAL SECURED</span></div></div></main>;
}
