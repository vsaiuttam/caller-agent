import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { LazyMotion, MotionConfig, domAnimation } from "framer-motion";
import App from "./App";
import { AuthProvider } from "./auth";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ThemeProvider } from "./theme";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* `m` components + domAnimation keep framer-motion's footprint small;
        reducedMotion="user" makes every animation honour the OS setting. */}
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">
        <ErrorBoundary>
          <BrowserRouter>
            <ThemeProvider>
              <AuthProvider>
                <App />
              </AuthProvider>
            </ThemeProvider>
          </BrowserRouter>
        </ErrorBoundary>
      </MotionConfig>
    </LazyMotion>
  </StrictMode>,
);
