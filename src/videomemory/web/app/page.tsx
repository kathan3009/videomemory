import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  Clock3,
  FileStack,
  Film,
  GitBranch,
  KeyRound,
  MessageSquareText,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { Brand } from './components/Mark';

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080').replace(/\/$/, '');
const MCP_URL = process.env.NEXT_PUBLIC_MCP_URL || `${API_URL}/mcp`;

const outcomes = [
  {
    icon: Search,
    label: 'Find the moment',
    title: 'Ask the video, not the timeline.',
    body: 'Search speech and what is happening on screen. Open the exact timestamp, frame, and surrounding transcript.',
    detail: 'Question → evidence → exact moment',
  },
  {
    icon: GitBranch,
    label: 'Keep the thinking',
    title: 'Turn every search into memory.',
    body: 'Questions, discoveries, and branched notes stay connected to the video instead of disappearing with the chat.',
    detail: 'Moment → note → revised note',
  },
  {
    icon: FileStack,
    label: 'Remember what shipped',
    title: 'Never lose an artifact again.',
    body: 'Remember what an agent created, where it lives, how to open it, and which version the team should use.',
    detail: 'Artifact → location → next agent',
  },
];

const plans = [
  { name: 'Free', price: '$0', note: 'Start building your memory.', limits: ['5 videos each month', '60 indexed minutes', '200 agent calls'], featured: false },
  { name: 'Creator', price: '$12', note: 'For research that happens every day.', limits: ['100 videos each month', '1,200 indexed minutes', '5,000 agent calls'], featured: true },
  { name: 'Studio', price: '$29', note: 'For teams with a growing library.', limits: ['1,000 videos each month', '10,000 indexed minutes', '50,000 agent calls'], featured: false },
];

export default function Home() {
  return (
    <main className="site-shell landing-shell">
      <nav className="nav-wrap landing-nav" aria-label="Main navigation">
        <Brand />
        <div className="nav-links">
          <a href="#memory">Memory</a>
          <a href="#connect">Connect</a>
          <a href="#pricing">Pricing</a>
          <a className="nav-login" href="/login">Sign in</a>
          <a className="nav-cta" href="/signup">Start free <ArrowUpRight size={14} aria-hidden="true" /></a>
        </div>
      </nav>

      <section className="landing-hero">
        <div className="hero-copy">
          <p className="landing-kicker"><Film size={13} aria-hidden="true" /> Memory for the work inside video</p>
          <h1>Your videos remember everything. <em>Now your agents can too.</em></h1>
          <p className="hero-lede">
            Ask Claude, Codex, Cursor, or any MCP client. Get the exact moment, frame, and transcript—plus
            every note and artifact your team has built around it.
          </p>
          <div className="hero-actions">
            <a className="button button-primary" href="/signup">Build your memory <ArrowRight size={16} aria-hidden="true" /></a>
            <a className="button button-ghost" href="#memory">See how it compounds</a>
          </div>
          <div className="hero-trust" aria-label="Product highlights">
            <span><Check size={13} /> Start free</span>
            <span><Check size={13} /> Uploads and links</span>
            <span><Check size={13} /> Works over MCP</span>
          </div>
        </div>

        <div className="memory-canvas" aria-label="An example of a video becoming connected memory">
          <div className="canvas-topbar">
            <span><i /> PRODUCT_REVIEW.MP4</span>
            <span>38:12 · INDEXED</span>
          </div>
          <div className="video-memory-strip" aria-hidden="true">
            <span className="strip-frame strip-a" />
            <span className="strip-frame strip-b" />
            <span className="strip-frame strip-c" />
            <span className="strip-frame strip-d" />
            <i className="playhead" />
          </div>
          <div className="memory-question">
            <MessageSquareText size={16} aria-hidden="true" />
            <span>Where do they explain why retention dropped?</span>
          </div>
          <div className="memory-answer">
            <div><Clock3 size={15} aria-hidden="true" /><strong>24:08</strong><span>Exact moment</span></div>
            <p>“The first-session setup asked for too much before the user saw value.”</p>
            <small>Transcript + visual evidence</small>
          </div>
          <div className="memory-branch memory-note">
            <GitBranch size={15} aria-hidden="true" />
            <span><b>Note · v2</b>Move setup after the first win.</span>
          </div>
          <div className="memory-branch memory-artifact">
            <FileStack size={15} aria-hidden="true" />
            <span><b>Artifact</b>onboarding-v3.fig · ready for review</span>
          </div>
          <span className="trace trace-one" aria-hidden="true" />
          <span className="trace trace-two" aria-hidden="true" />
          <span className="canvas-caption">One question, with all the work around it.</span>
        </div>
      </section>

      <section className="signal-bar" aria-label="How VideoMemory works">
        <span>Add the video</span><ArrowRight size={15} />
        <span>Ask naturally</span><ArrowRight size={15} />
        <span>Open the evidence</span><ArrowRight size={15} />
        <span>Keep the context</span>
      </section>

      <section className="outcomes-section" id="memory">
        <div className="section-heading">
          <p className="landing-kicker">A memory that compounds</p>
          <h2>The second question should be smarter than the first.</h2>
          <p>VideoMemory keeps the useful trail—not just a summary—so every search starts with what your team already knows.</p>
        </div>
        <div className="outcome-grid">
          {outcomes.map(({ icon: Icon, label, title, body, detail }) => (
            <article className="outcome-card" key={label}>
              <div className="outcome-label"><Icon size={18} strokeWidth={1.6} aria-hidden="true" /><span>{label}</span></div>
              <h3>{title}</h3>
              <p>{body}</p>
              <small>{detail}</small>
            </article>
          ))}
        </div>
      </section>

      <section className="continuity-section">
        <div className="continuity-copy">
          <p className="landing-kicker">Context that survives the chat</p>
          <h2>From a moment in a video to the next thing your team ships.</h2>
          <p>
            A useful answer rarely ends at the timestamp. It becomes a decision, a note, a design, or a piece of code.
            VideoMemory keeps that chain intact across people and agents.
          </p>
          <a className="text-link" href="/signup">Create a shared memory <ArrowUpRight size={14} aria-hidden="true" /></a>
        </div>
        <div className="memory-ledger">
          <article><time>Today · 10:42</time><div><Film size={17} /><span><b>Product review added</b>38 minutes of searchable context</span></div></article>
          <article><time>Today · 11:06</time><div><MessageSquareText size={17} /><span><b>Moment recalled</b>Retention drop explained at 24:08</span></div></article>
          <article><time>Today · 11:18</time><div><GitBranch size={17} /><span><b>Decision branched</b>Onboarding direction revised to v2</span></div></article>
          <article className="ledger-future"><time>Next session</time><div><Bot size={17} /><span><b>Context already here</b>Your next agent starts from the decision</span></div></article>
        </div>
      </section>

      <section className="connect-section" id="connect">
        <div className="connect-heading">
          <p className="landing-kicker">Bring the agent you already use</p>
          <h2>One connection. No context handoff.</h2>
          <p>Create a private key, add the MCP endpoint, and your agent can search video memory and artifact memory in the same conversation.</p>
          <div className="connection-benefits">
            <span><KeyRound size={15} /> Revocable access</span>
            <span><Bot size={15} /> Claude, Codex, Cursor, and more</span>
          </div>
        </div>
        <div className="connection-window">
          <div className="connection-title"><span>CODEX · config.toml</span><span>READY</span></div>
          <pre><code>[mcp_servers.videomemory]{`\n`}url = &quot;{MCP_URL}&quot;{`\n`}bearer_token_env_var = &quot;VIDEOMEMORY_TOKEN&quot;</code></pre>
          <div className="connection-result"><ShieldCheck size={15} aria-hidden="true" /><span>Video and artifact memory available in your agent</span></div>
        </div>
      </section>

      <section className="privacy-strip" aria-label="Privacy and security">
        <div><ShieldCheck size={22} aria-hidden="true" /><h3>Your workspace stays yours.</h3></div>
        <p>Private libraries, revocable agent keys, guarded uploads, and validated external links—without turning the landing page into a security manual.</p>
        <a href="/privacy">Read the privacy details <ArrowUpRight size={14} /></a>
      </section>

      <section className="pricing-section" id="pricing">
        <div className="pricing-head">
          <p className="landing-kicker">Start small. Keep what becomes valuable.</p>
          <h2>A free memory first. More room when you need it.</h2>
          <p>No card to start. All plans include uploads, links, agent access, notes, and artifact memory.</p>
        </div>
        <div className="pricing-grid">
          {plans.map((plan) => (
            <article className={plan.featured ? 'price-card featured' : 'price-card'} key={plan.name}>
              {plan.featured && <span className="popular">Most useful</span>}
              <span className="price-name">{plan.name}</span>
              <div className="price"><strong>{plan.price}</strong><span>/ month</span></div>
              <p>{plan.note}</p>
              <ul>{plan.limits.map((limit) => <li key={limit}><Check size={14} />{limit}</li>)}</ul>
              <a className={plan.featured ? 'button button-primary' : 'button button-ghost'} href={`/signup?plan=${plan.name.toLowerCase()}`}>Start free <ArrowRight size={15} /></a>
            </article>
          ))}
        </div>
      </section>

      <section className="final-cta">
        <p className="landing-kicker">Your next question already has a history.</p>
        <h2>Give your videos<br /><em>a memory.</em></h2>
        <p>Start with one upload. Connect your agent when you are ready.</p>
        <a className="button button-primary" href="/signup">Start building <ArrowUpRight size={16} /></a>
      </section>

      <footer>
        <Brand />
        <p>Video memory for people who build with agents.</p>
        <div><a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="mailto:kthndesai@gmail.com">Contact</a><a href="https://github.com/kathan3009/videomemory">GitHub</a></div>
      </footer>
    </main>
  );
}
