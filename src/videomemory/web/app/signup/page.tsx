import { AuthForm } from '../components/AuthForm';
import { Brand } from '../components/Mark';

export default function SignupPage() {
  return (
    <main className="auth-shell">
      <div className="noise" aria-hidden="true" />
      <nav className="auth-nav"><Brand /><a href="/login">Sign in</a></nav>
      <div className="auth-grid">
        <AuthForm mode="signup" />
        <div className="auth-art" aria-hidden="true"><div className="auth-orbit auth-orbit-a" /><div className="auth-orbit auth-orbit-b" /><div className="auth-time">00:00</div><span>MEMORY STARTS HERE</span></div>
      </div>
    </main>
  );
}
