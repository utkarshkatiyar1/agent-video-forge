import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "AgentVideoForge", description: "Agentic prompt-to-video pipeline" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
