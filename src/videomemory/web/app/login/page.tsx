import { AuthForm } from '../components/AuthForm';
import { Brand } from '../components/Mark';

export default function LoginPage() {
  return (
    <main className="auth-shell">
      <div className="noise" aria-hidden="true" />
      <nav className="auth-nav"><Brand /><a href="/signup">Create account</a></nav>
      <div className="auth-grid">
        <AuthForm mode="login" />
        <div className="auth-art" aria-hidden="true"><div className="auth-orbit auth-orbit-a" /><div className="auth-orbit auth-orbit-b" /><div className="auth-time">14:23</div><span>MEMORY FOUND</span></div>
      </div>
    </main>
  );
}
