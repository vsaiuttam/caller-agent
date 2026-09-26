/**
 * Everything the console needs and the public pages don't: the shared data
 * (health, stats, live calls and the event socket), the shell, and a page
 * skeleton while each page's chunk streams in. Lazy-loaded by App.tsx.
 */

import { Suspense } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { DataProvider } from "../../data";
import { ErrorBoundary } from "../ErrorBoundary";
import { Skeleton } from "../ui";
import { AppShell } from "./AppShell";

export default function ConsoleLayout() {
  const location = useLocation();
  return (
    <DataProvider>
      <AppShell>
        <ErrorBoundary resetKey={location.pathname}>
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </AppShell>
    </DataProvider>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-6 sm:px-6 lg:px-8" aria-busy="true" aria-label="Loading page">
      <Skeleton className="h-7 w-48" />
      <Skeleton className="mt-2.5 h-4 w-80 max-w-full" />
      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <Skeleton className="mt-3 h-72 rounded-xl" />
    </div>
  );
}
