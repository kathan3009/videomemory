import { Brand, Mark } from './components/Mark';

const planes = [
  { label: 'TRANSCRIPT', time: '14:23', className: 'plane plane-one' },
  { label: 'VISION', time: '14:21', className: 'plane plane-two' },
  { label: 'MOMENT', time: '14:18', className: 'plane plane-three' },
];

const capabilities = [
  ['skip', 'Ask a question. Land on the second that answers it.'],
  ['look', 'Search what happens on screen, even without dialogue.'],
  ['understand', 'Turn a long video into chapters, evidence, and a usable brief.'],
  ['search', 'Recall a moment across every video in your private library.'],
  ['shots', 'Detect frame-accurate scene boundaries for editing workflows.'],
  ['cutpoints', 'Align motion-aware cuts to the beat of a soundtrack.'],
  ['memory', 'Recall prior searches, videos, moments, and the paths between them.'],
  ['note', 'Branch versioned thoughts from any video without losing the earlier idea.'],
];

const plans = [
  { name: 'Free', price: '$0', note: 'For your first useful memory', limits: ['5 videos / month', '60 indexed minutes', '200 MCP calls'], cta: 'Start free', featured: false },
  { name: 'Creator', price: '$12', note: 'For daily research and production', limits: ['100 videos / month', '1,200 indexed minutes', '5,000 MCP calls'], cta: 'Choose Creator', featured: true },
  { name: 'Studio', price: '$29', note: 'For serious video workflows', limits: ['1,000 videos / month', '10,000 indexed minutes', '50,000 MCP calls'], cta: 'Choose Studio', featured: false },
];

export default function Home() {
  return (
    <main className="site-shell">
      <div className="noise" aria-hidden="true" />
      <nav className="nav-wrap" aria-label="Main navigation">
        <Brand />
        <div className="nav-links">
          <a href="#product">Product</a>
          <a href="#security">Security</a>
          <a href="#pricing">Pricing</a>
          <a href="/login">Sign in</a>
          <a className="nav-cta" href="/signup">Start free</a>
        </div>
      </nav>

      <section className="hero" id="top">
        <div className="hero-copy">
          <div className="eyebrow"><span className="status-dot" /> MCP-native video intelligence</div>
          <h1>Every video.<br /><span>Immediately useful.</span></h1>
          <p className="hero-lede">
            Give Claude and Codex a searchable memory for video. Ask a question, jump to the exact
            moment, inspect the frame, and keep the answer in your private library.
          </p>
          <div className="hero-actions">
            <a className="button button-primary" href="/signup">Build your video memory <span>↗</span></a>
            <a className="button button-ghost" href="#demo"><span className="play">▶</span> See it work</a>
          </div>
          <div className="proof-line">
            <span>Free to start</span><i />
            <span>Any public video URL</span><i />
            <span>Private by default</span>
          </div>
        </div>

        <div className="memory-stage" aria-label="A three-dimensional stack of indexed video moments">
          <div className="orbit orbit-one" aria-hidden="true" />
          <div className="orbit orbit-two" aria-hidden="true" />
          <div className="plane-stack">
            {planes.map((plane, index) => (
              <div className={plane.className} key={plane.label}>
                <div className="plane-topline"><span>{plane.label}</span><span>0{index + 1}</span></div>
                <div className="frame-art">
                  <span className="frame-subject" />
                  <span className="frame-horizon" />
                  <span className="scan-line" />
                </div>
                <div className="plane-caption">
                  <strong>{plane.time}</strong>
                  <span>{index === 0 ? 'The exact answer, found.' : index === 1 ? 'Visual signal matched.' : 'Context indexed.'}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="stage-label stage-label-left"><span>INDEX</span><strong>384D</strong></div>
          <div className="stage-label stage-label-right"><span>LATENCY</span><strong>0.42s</strong></div>
        </div>
      </section>

      <section className="command-demo" id="demo" aria-label="Videomemory example">
        <div className="command-head">
          <span><i className="status-dot" /> AGENT SESSION</span>
          <span>VIDEOMEMORY / SKIP</span>
        </div>
        <div className="command-body">
          <span className="prompt">›</span>
          <p>Skip to where they explain why the database migration failed.</p>
          <div className="result-pill"><b>14:23</b><span>Exact moment found</span><em>Open frame ↗</em></div>
        </div>
      </section>

      <section className="manifesto" id="product">
        <p className="section-kicker">THE MEMORY LAYER</p>
        <div className="manifesto-grid">
          <h2>Stop rewatching.<br />Start recalling.</h2>
          <div>
            <p>Videomemory watches the pixels, hears the words, and preserves the timeline. Your agent gets evidence—not another vague summary.</p>
            <span className="inline-rule" />
            <small>One private context graph. Eleven purpose-built tools. Every result linked back to its moment.</small>
          </div>
        </div>
      </section>

      <section className="capability-grid" aria-label="Videomemory capabilities">
        {capabilities.map(([name, description], index) => (
          <article className="capability-card" key={name}>
            <div className="capability-index">0{index + 1}</div>
            <div className="capability-symbol" aria-hidden="true"><span /><i /></div>
            <h3>{name}</h3>
            <p>{description}</p>
          </article>
        ))}
      </section>

      <section className="agent-connect">
        <div className="connect-copy">
          <p className="section-kicker">ONE ENDPOINT</p>
          <h2>Already speaks<br />your agent&apos;s language.</h2>
          <p>Connect once with a private MCP key. Claude Code, Codex, and compatible clients immediately get every Videomemory tool.</p>
          <a className="text-link" href="/signup">Create your endpoint <span>↗</span></a>
        </div>
        <div className="code-window">
          <div className="code-tabs"><span className="active">CLAUDE</span><span>CODEX</span><em>● SECURE</em></div>
          <pre><code><span className="code-muted">$</span> claude mcp add --transport http{`\n`}  videomemory https://mcp.videomemory.ai/mcp{`\n`}  <span className="code-muted">--header</span> <span className="code-string">&quot;Authorization: Bearer vm_live_••••&quot;</span></code></pre>
          <div className="code-status"><span className="status-dot" /> Connected · 11 tools available</div>
        </div>
      </section>

      <section className="security-section" id="security">
        <div className="security-visual" aria-hidden="true">
          <div className="vault-ring vault-ring-one" />
          <div className="vault-ring vault-ring-two" />
          <Mark />
          <span className="vault-label vault-a">TENANT / 7F2A</span>
          <span className="vault-label vault-b">ISOLATED</span>
        </div>
        <div className="security-copy">
          <p className="section-kicker">PRIVATE BY ARCHITECTURE</p>
          <h2>Your memory is not<br />someone else&apos;s context.</h2>
          <p>Every account resolves to a separate data root. Passwords, sessions, and MCP keys are stored only as hardened hashes. Public URL validation blocks local networks and cloud metadata before the downloader starts.</p>
          <ul>
            <li><span>01</span> Tenant-scoped storage and queries</li>
            <li><span>02</span> Revocable, hashed MCP credentials</li>
            <li><span>03</span> Signed billing webhooks and strict origins</li>
          </ul>
        </div>
      </section>

      <section className="pricing-section" id="pricing">
        <div className="pricing-head">
          <p className="section-kicker">SIMPLE MONTHLY PRICING</p>
          <h2>Build the memory.<br /><span>Upgrade when it earns its place.</span></h2>
          <p>Prices shown in USD. International payments are securely processed by Razorpay.</p>
        </div>
        <div className="pricing-grid">
          {plans.map((plan) => (
            <article className={plan.featured ? 'price-card featured' : 'price-card'} key={plan.name}>
              {plan.featured && <div className="popular">MOST USEFUL</div>}
              <div className="price-name">{plan.name}</div>
              <div className="price"><strong>{plan.price}</strong><span>/ month</span></div>
              <p>{plan.note}</p>
              <ul>{plan.limits.map((limit) => <li key={limit}><span>✓</span>{limit}</li>)}</ul>
              <a className={plan.featured ? 'button button-primary' : 'button button-ghost'} href="/signup">{plan.cta}</a>
            </article>
          ))}
        </div>
      </section>

      <section className="final-cta">
        <div><Mark /></div>
        <p className="section-kicker">THE VIDEO WAS THE DATABASE</p>
        <h2>Now your agent<br />can query it.</h2>
        <a className="button button-primary" href="/signup">Start with five videos <span>↗</span></a>
      </section>

      <footer>
        <Brand />
        <p>Built by Kathan Desai · India / Internet</p>
        <div><a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="mailto:kthndesai@gmail.com">Contact</a><a href="https://github.com/kathan3009/videomemory">GitHub</a><a href="/login">Sign in</a></div>
      </footer>
    </main>
  );
}
