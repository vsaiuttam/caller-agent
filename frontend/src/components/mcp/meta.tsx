/**
 * What the connected-apps screens say about servers: the presets in the
 * connect dialog, each server's glyph and transport label, URL checks, and
 * a plain-language hint for every way connecting can fail.
 */

import type { ReactNode } from "react";
import type { McpServer, McpTransport } from "../../api";
import { IconBolt, IconDashboard, IconPlug, IconSparkle } from "../icons";

export type PresetId = "demo" | "zapier" | "composio" | "custom";

export interface Preset {
  id: PresetId;
  title: string;
  tagline: string;
  /** Where to find the URL — shown above the form. */
  where: ReactNode;
  defaultName: string;
  urlPlaceholder: string;
  icon: ReactNode;
}

export const DEMO_URL = "builtin://demo";

export const PRESETS: Preset[] = [
  {
    id: "demo",
    title: "Demo CRM",
    tagline: "Built in · one click. Fake customers, slots and tickets.",
    where: "Runs inside Samvaad — no account, no network.",
    defaultName: "Demo CRM",
    urlPlaceholder: DEMO_URL,
    icon: <IconSparkle size={18} />,
  },
  {
    id: "zapier",
    title: "Zapier MCP",
    tagline: "Thousands of apps through one server.",
    where: (
      <>
        At <span className="font-medium text-ink">mcp.zapier.com</span>, open your MCP server, add the actions the agent may
        use, then copy the server URL from its Connect tab. The URL contains your key — treat it like a password.
      </>
    ),
    defaultName: "Zapier",
    urlPlaceholder: "https://mcp.zapier.com/api/mcp/…",
    icon: <IconBolt size={18} />,
  },
  {
    id: "composio",
    title: "Composio",
    tagline: "Hundreds of toolkits with managed sign-in.",
    where: (
      <>
        In the <span className="font-medium text-ink">Composio</span> dashboard, create an MCP server for the toolkits you
        want and copy its URL. If it asks for an API key, add it as a header below.
      </>
    ),
    defaultName: "Composio",
    urlPlaceholder: "https://mcp.composio.dev/…",
    icon: <IconDashboard size={18} />,
  },
  {
    id: "custom",
    title: "Any MCP server",
    tagline: "Your own, or any Streamable HTTP / SSE endpoint.",
    where: (
      <>
        Paste the server's endpoint — it usually ends in <code className="font-mono">/mcp</code> (or{" "}
        <code className="font-mono">/sse</code>). Most servers want a key in an{" "}
        <code className="font-mono">Authorization</code> header.
      </>
    ),
    defaultName: "",
    urlPlaceholder: "https://example.com/mcp",
    icon: <IconPlug size={18} />,
  },
];

export const TRANSPORT_LABEL: Record<McpTransport, string> = {
  builtin: "Built in",
  streamable_http: "Streamable HTTP",
  sse: "SSE",
};

/** A glyph that hints at where the server lives. Never a brand logo. */
export function serverIcon(server: McpServer, size = 17): ReactNode {
  if (server.transport === "builtin") return <IconSparkle size={size} />;
  if (/zapier/i.test(server.host)) return <IconBolt size={size} />;
  if (/composio/i.test(server.host)) return <IconDashboard size={size} />;
  return <IconPlug size={size} />;
}

/** Blocking problems with a server URL, and a softer warning for plain http. */
export function checkServerUrl(raw: string): { error?: string; warning?: string } {
  const url = raw.trim();
  if (!url) return { error: "Paste the server's URL." };
  if (url === DEMO_URL) return {};
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { error: "That isn't a full address — it should start with https://" };
  }
  if (parsed.protocol === "http:") {
    return { warning: "Plain http is refused unless the backend allows private hosts. Use https:// if the server supports it." };
  }
  if (parsed.protocol !== "https:") return { error: "Only https:// addresses can be connected." };
  return {};
}

/** Why connecting failed, in words someone can act on. Null when we can't tell. */
export function connectHint(message: string, status?: number): string | null {
  const text = message.toLowerCase();
  if (status === 400 || /unsafe|private|loopback|link-local|reserved|not allowed/.test(text)) {
    return "For safety, the agent only connects to public https:// addresses — never localhost or a private network. Running a server locally? Set MCP_ALLOW_PRIVATE_HOSTS=true on the backend (development only).";
  }
  if (/re-enter|decrypt|secrets/.test(text)) {
    return "The saved credentials can't be read any more — usually because SECRETS_KEY changed. Edit the server and replace its URL and headers.";
  }
  if (/\b40[13]\b|unauthori[sz]ed|forbidden|auth|api key|credential|token/.test(text)) {
    return "The server turned the credentials down. Check the key — most servers expect an Authorization header of “Bearer <key>”, and some put the key in the URL itself.";
  }
  if (/timed? ?out|timeout|unreachable|refused|resolve|dns|getaddrinfo|name or service|network|connect/.test(text)) {
    return "Couldn't reach it. Check the URL for typos, and that the server is up and reachable from the internet.";
  }
  if (/not an mcp|\b40[456]\b|content-type|html|unexpected/.test(text)) {
    return "Something answered, but not as an MCP server. Check the path — it usually ends in /mcp or /sse — or pick the transport under Advanced.";
  }
  return null;
}
