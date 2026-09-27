import { useState } from "react";
import { api, campaignTools, unlessMissing, type McpServer } from "../../api";
import { useHealth } from "../../data";
import { CampaignToolsCard } from "../mcp/CampaignTools";
import { ConnectDialog, type ConnectIntent } from "../mcp/ConnectDialog";
import { useBuilder } from "./context";

/**
 * Step 3. "Connect an app" opens the same connect flow as Integrations, over
 * the builder: the draft stays where it is, and the new app's tools show up
 * in the picker as soon as it connects.
 */
export function ToolsStep() {
  const { draft, setForm } = useBuilder();
  const { reload: reloadHealth } = useHealth();
  const [intent, setIntent] = useState<ConnectIntent | null>(null);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  const open = async () => {
    setIntent("pick");
    try {
      setServers((await unlessMissing(api.mcpServers())) ?? []);
    } catch {
      setServers([]);
    }
  };

  return (
    <>
      <CampaignToolsCard
        value={campaignTools(draft.form)}
        onChange={(next) => setForm(next)}
        onConnect={() => void open()}
        reloadKey={reloadKey}
      />
      <ConnectDialog
        intent={intent}
        servers={servers}
        onClose={() => setIntent(null)}
        onSaved={(server) => {
          setServers((prev) => [...prev.filter((s) => s.id !== server.id), server]);
          setReloadKey((k) => k + 1);
          reloadHealth();
        }}
        onRemoved={(id) => {
          setServers((prev) => prev.filter((s) => s.id !== id));
          setReloadKey((k) => k + 1);
        }}
      />
    </>
  );
}
