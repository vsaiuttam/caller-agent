import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { DataProvider } from "./data";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Logo } from "./components/Logo";
import { AppShell } from "./components/shell/AppShell";
import { Skeleton, Toaster } from "./components/ui";

// Every page is its own chunk: the shell paints first, pages stream in.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Campaigns = lazy(() => import("./pages/Campaigns"));
const CampaignDetail = lazy(() => import("./pages/CampaignDetail"));
const NewCampaign = lazy(() => import("./pages/NewCampaign"));
const Calls = lazy(() => import("./pages/Calls"));
const Live = lazy(() => import("./pages/Live"));
const TestLab = lazy(() => import("./pages/TestLab"));
const Simulator = lazy(() => import("./pages/Simulator"));
const PhoneTest = lazy(() => import("./pages/PhoneTest"));
const LiveMic = lazy(() => import("./pages/LiveMic"));
const Templates = lazy(() => import("./pages/Templates"));
const Models = lazy(() => import("./pages/Models"));
const Settings = lazy(() => import("./pages/Settings"));
const Suppressions = lazy(() => import("./pages/Suppressions"));
const Login = lazy(() => import("./pages/Login"));
const NotFound = lazy(() => import("./pages/NotFound"));

export default function App() {
  const auth = useAuth();
  const location = useLocation();

  if (auth.phase === "checking") return <Splash />;

  if (auth.phase === "locked") {
    return (
      <>
        <Suspense fallback={<Splash />}>
          <Login />
        </Suspense>
        <Toaster />
      </>
    );
  }

  return (
    <DataProvider>
      <AppShell>
        <ErrorBoundary resetKey={location.pathname}>
          <Suspense fallback={<PageSkeleton />}>
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/campaigns" element={<Campaigns />} />
              <Route path="/campaigns/new" element={<NewCampaign />} />
              <Route path="/campaigns/:id" element={<CampaignDetail />} />
              <Route path="/calls" element={<Calls />} />
              <Route path="/review" element={<Calls reviewOnly />} />
              <Route path="/live" element={<Live />} />
              <Route path="/test-lab" element={<TestLab />}>
                <Route index element={<Simulator />} />
                <Route path="phone" element={<PhoneTest />} />
                <Route path="mic" element={<LiveMic />} />
              </Route>
              {/* v1 paths, so old bookmarks still land somewhere sensible */}
              <Route path="/simulator" element={<Navigate to="/test-lab" replace />} />
              <Route path="/templates" element={<Templates />} />
              <Route path="/models" element={<Models />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/suppressions" element={<Suppressions />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </AppShell>
      <Toaster />
    </DataProvider>
  );
}

function Splash() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5" aria-busy="true" aria-label="Loading">
      <Logo size={36} />
      <Skeleton className="h-1.5 w-40 rounded-full" />
    </div>
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
