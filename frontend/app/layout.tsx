import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "VideoMemory",
  description: "Video memory operating system for AI agents",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="mx-auto max-w-6xl px-6 py-8">
          <header className="mb-8 flex items-center gap-3">
            <span className="inline-block h-3 w-3 rounded-full bg-emerald-400" />
            <h1 className="text-xl font-semibold tracking-tight">VideoMemory</h1>
            <span className="text-sm text-slate-400">video memory for AI agents</span>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
