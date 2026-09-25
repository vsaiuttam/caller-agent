import { Dialog, Button, Kbd } from "./ui";
import { NAV_ITEMS } from "./shell/nav";

export const MOD_KEY = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl";

const GENERAL: Array<[string[], string]> = [
  [[MOD_KEY, "K"], "Open the command palette"],
  [["/"], "Search"],
  [["?"], "Show this list"],
  [["["], "Collapse or expand the sidebar"],
  [["Esc"], "Close a dialog or drawer"],
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Keyboard shortcuts"
      description="Everything in the console is reachable from the keyboard."
      footer={<Button variant="secondary" onClick={onClose}>Done</Button>}
    >
      <div className="grid gap-6 sm:grid-cols-2">
        <section>
          <h3 className="mb-2 text-2xs font-medium uppercase tracking-wider text-ink-muted">General</h3>
          <ul className="space-y-2">
            {GENERAL.map(([keys, what]) => (
              <Row key={what} keys={keys} what={what} />
            ))}
          </ul>
        </section>
        <section>
          <h3 className="mb-2 text-2xs font-medium uppercase tracking-wider text-ink-muted">Go to</h3>
          <ul className="space-y-2">
            {NAV_ITEMS.map((item) => (
              <Row key={item.to} keys={["G", item.key.toUpperCase()]} what={item.label} />
            ))}
          </ul>
        </section>
      </div>
    </Dialog>
  );
}

function Row({ keys, what }: { keys: string[]; what: string }) {
  return (
    <li className="flex items-center justify-between gap-3 text-sm text-ink-secondary">
      <span>{what}</span>
      <span className="flex shrink-0 items-center gap-1">
        {keys.map((k, i) => (
          <Kbd key={i}>{k}</Kbd>
        ))}
      </span>
    </li>
  );
}
