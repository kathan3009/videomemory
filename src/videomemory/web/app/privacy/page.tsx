import Link from 'next/link';
import { Brand } from '../components/Mark';

export default function PrivacyPage() {
  return (
    <main className="legal-shell">
      <nav className="auth-nav"><Brand /><Link href="/">Back home</Link></nav>
      <article className="legal-copy">
        <p className="section-kicker">PRIVACY POLICY · AUGUST 29, 2026</p>
        <h1>Your video memory stays yours.</h1>
        <p>Videomemory is operated by Kathan Desai. This policy explains what we collect when you use the hosted service and why.</p>
        <h2>Information we collect</h2>
        <p>We store the name and email you provide, a hardened password hash, hashed session and MCP credentials, billing status, product usage, video URLs or files you submit, and the transcripts, searches, notes, indexes, and frames created from them. Raw credentials and card details are not stored by Videomemory.</p>
        <h2>How it is used</h2>
        <p>We use this information only to operate, secure, support, bill, and improve the service. We do not sell personal data or use private video indexes to train shared models.</p>
        <h2>Processors and retention</h2>
        <p>Infrastructure providers may process data on our behalf, including OpenAI Sites or Cloudflare for the web application, Railway for the API, and our payment provider for billing. When AI summaries are enabled, the transcript needed for that request may also be processed by Anthropic or OpenAI. Video files, derived indexes, searches, and notes are retained while they remain in your account; deleting a video removes its live stored memory and associated raw upload.</p>
        <h2>Your choices</h2>
        <p>You can revoke MCP keys from the dashboard. To export or delete your hosted account and associated video memory, email <a href="mailto:kthndesai@gmail.com">kthndesai@gmail.com</a> from the address on the account.</p>
        <h2>Contact</h2>
        <p>Questions or privacy requests: <a href="mailto:kthndesai@gmail.com">Kathan Desai · kthndesai@gmail.com</a>.</p>
      </article>
    </main>
  );
}
