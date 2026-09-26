/**
 * The product's name and voice, in one place. A rename is a one-file change:
 * everything user-facing that says the name reads it from here (the favicon
 * and <title> in index.html are the only other spots, and they are static).
 */

const NAME = "Samvaad";
const REPO = "https://github.com/vsaiuttam/caller-agent";

export const BRAND = {
  name: NAME,
  /** संवाद, "conversation". Shown as a quiet subtitle, never instead of the name. */
  nativeName: "संवाद",
  meaning: "conversation",
  tagline: "AI voice agents that sound human.",
  description:
    "Design a calling campaign, rehearse it, then watch every conversation happen live. Transcripts, outcomes and follow-ups are saved for you.",
  /** Used by the agent character's accessible label. */
  agentName: `${NAME} agent`,
  copyright: `© ${new Date().getFullYear()} ${NAME}`,
  repoUrl: REPO,
  /** The README is the documentation. */
  docsUrl: `${REPO}#readme`,
  setupUrl: `${REPO}#running-it`,
  complianceUrl: `${REPO}#before-dialling-real-numbers`,
  /** The languages the agent's stock lines and templates are written in. */
  languages: [
    { code: "en", name: "English", native: "English", dir: "ltr" },
    { code: "hi", name: "Hindi", native: "हिन्दी", dir: "ltr" },
    { code: "ur", name: "Urdu", native: "اردو", dir: "rtl" },
    { code: "hi-Latn", name: "Hinglish", native: "Hinglish", dir: "ltr" },
  ],
} as const;
