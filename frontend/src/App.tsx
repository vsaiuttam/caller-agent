/**
 * The route map.
 *
 *   /            the marketing page (public)
 *   /login       sign-in (public; sends signed-in people straight on)
 *   /app/*       the console, behind RequireConsole
 *   v1 paths     redirect to their /app twin with query string and hash kept
 *
 * Every page is its own chunk, and so is the console frame, so the landing
 * page never downloads the console and the console never downloads the
 * landing page.
 */

import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { Logo } from "./components/Logo";
import { Skeleton, Toaster } from "./components/ui";
import { APP, LEGACY_SECTIONS, loginFor } from "./routes";

const Landing = lazy(() => import("./pages/Landing"));
const Login = lazy(() => import("./pages/Login"));
const ConsoleLayout = lazy(() => import("./components/shell/ConsoleLayout"));

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
const NotFound = lazy(() => import("./pages/NotFound"));

export default function App() {
  return (
    <>
      <Suspense fallback={<Splash />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />

          <Route path={APP} element={<RequireConsole />}>
            <Route index element={<Dashboard />} />
            <Route path="dashboard" element={<Moved to={APP} />} />
            <Route path="campaigns" element={<Campaigns />} />
            <Route path="campaigns/new" element={<NewCampaign />} />
            <Route path="campaigns/:id" element={<CampaignDetail />} />
            <Route path="calls" element={<Calls />} />
            <Route path="review" element={<Calls reviewOnly />} />
            <Route path="live" element={<Live />} />
            <Route path="test-lab" element={<TestLab />}>
              <Route index element={<Simulator />} />
              <Route path="phone" element={<PhoneTest />} />
              <Route path="mic" element={<LiveMic />} />
            </Route>
            <Route path="simulator" element={<Moved to={`${APP}/test-lab`} />} />
            <Route path="templates" element={<Templates />} />
            <Route path="models" element={<Models />} />
            <Route path="settings" element={<Settings />} />
            <Route path="suppressions" element={<Suppressions />} />
            <Route path="*" element={<NotFound />} />
          </Route>

          {/* v1 paths: the console used to live at the root. */}
          <Route path="/dashboard" element={<Moved to={APP} />} />
          <Route path="/simulator" element={<Moved to={`${APP}/test-lab`} />} />
          {LEGACY_SECTIONS.map((section) => (
            <Route key={section} path={`/${section}/*`} element={<Moved />} />
          ))}

          <Route path="*" element={<NotFound scope="site" />} />
        </Routes>
      </Suspense>
      <Toaster />
    </>
  );
}

/** The console needs an answer from /api/auth/status before it can open. */
function RequireConsole() {
  const { phase } = useAuth();
  const location = useLocation();
  if (phase === "checking") return <Splash />;
  if (phase === "locked") return <Navigate to={loginFor(location)} replace />;
  return <ConsoleLayout />;
}

/**
 * A permanent move. Without `to`, the path is prefixed with /app
 * (`/calls` → `/app/calls`); either way the query string and hash come along,
 * so `/calls?call=42` still opens call 42.
 */
function Moved({ to }: { to?: string }) {
  const location = useLocation();
  const pathname = to ?? `${APP}${location.pathname}`;
  return <Navigate to={{ pathname, search: location.search, hash: location.hash }} replace />;
}

function Splash() {
  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-5" aria-busy="true" aria-label="Loading">
      <Logo size={36} />
      <Skeleton className="h-1.5 w-40 rounded-full" />
    </div>
  );
}
