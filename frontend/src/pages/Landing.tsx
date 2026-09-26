import { Link } from "react-router-dom";
import { BRAND } from "../brand";
import { Logo } from "../components/Logo";

/** Placeholder until the landing page lands in the next commit. */
export default function Landing() {
  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 px-4 text-center">
      <Logo size={36} />
      <h1 className="text-display-lg font-semibold text-ink">{BRAND.tagline}</h1>
      <Link to="/login" className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-on-brand">
        Sign in to the console
      </Link>
    </main>
  );
}
