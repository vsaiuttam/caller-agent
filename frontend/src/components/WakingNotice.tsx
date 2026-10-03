/**
 * Shown while the first request is still out after a few seconds. The API
 * runs on a hosting plan that sleeps when idle, and the first visit after a
 * quiet spell waits ~70 s for it to boot; a skeleton alone looks broken.
 */

import { useEffect, useState } from "react";

export function WakingNotice({ afterMs = 3000 }: { afterMs?: number }) {
  const [shown, setShown] = useState(false);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const id = window.setInterval(() => {
      const elapsed = Date.now() - start;
      if (elapsed >= afterMs) setShown(true);
      setSeconds(Math.floor(elapsed / 1000));
    }, 500);
    return () => window.clearInterval(id);
  }, [afterMs]);

  if (!shown) return null;
  return (
    <p role="status" className="max-w-xs text-center text-sm text-ink-muted">
      Waking the server ({seconds}s). After a quiet spell this can take up to a minute.
    </p>
  );
}
