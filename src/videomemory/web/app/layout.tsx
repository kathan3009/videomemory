import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000'),
  applicationName: 'VideoMemory',
  alternates: { canonical: '/' },
  title: 'Videomemory — Every video, immediately useful',
  description: 'A private, searchable video memory for Claude, Codex, and every MCP-compatible agent.',
  icons: { icon: '/og.png' },
  openGraph: {
    title: 'Videomemory — Every video, immediately useful',
    description: 'A private, searchable video memory for Claude, Codex, and every MCP-compatible agent.',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'Videomemory — Every video. Immediately useful.' }],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Videomemory — Every video, immediately useful',
    description: 'A private, searchable video memory for Claude, Codex, and every MCP-compatible agent.',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
