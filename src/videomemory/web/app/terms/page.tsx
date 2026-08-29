import Link from 'next/link';
import { Brand } from '../components/Mark';

export default function TermsPage() {
  return (
    <main className="legal-shell">
      <nav className="auth-nav"><Brand /><Link href="/">Back home</Link></nav>
      <article className="legal-copy">
        <p className="section-kicker">TERMS OF SERVICE · AUGUST 29, 2026</p>
        <h1>Use video intelligently—and responsibly.</h1>
        <p>These terms govern your use of the Videomemory hosted service operated by Kathan Desai. By creating an account, you agree to them.</p>
        <h2>Your account</h2>
        <p>You are responsible for safeguarding your password and MCP keys and for activity performed with them. Provide accurate account information and notify us promptly if a credential may be compromised.</p>
        <h2>Video rights and acceptable use</h2>
        <p>Only submit videos you are authorized to access and process. Do not use Videomemory to infringe copyright, bypass access controls, invade privacy, distribute malware, probe private networks, or violate applicable law or a source platform’s terms.</p>
        <h2>Plans and billing</h2>
        <p>Free and paid plans have the published monthly limits. Paid subscriptions renew monthly until cancelled. Prices are shown in USD; your payment provider may present a local-currency conversion. Taxes and bank conversion fees may apply.</p>
        <h2>Availability and changes</h2>
        <p>The service is provided on an as-available basis. Video sources can change or block automated access, and machine-generated transcripts or visual matches may contain errors. We may modify features or limits and will give reasonable notice of material changes.</p>
        <h2>Termination and liability</h2>
        <p>We may suspend abusive or unlawful use. To the extent permitted by law, Videomemory is provided without warranties and liability is limited to the amount you paid for the service during the three months before a claim.</p>
        <h2>Contact</h2>
        <p>Questions: <a href="mailto:kthndesai@gmail.com">Kathan Desai · kthndesai@gmail.com</a>.</p>
      </article>
    </main>
  );
}
