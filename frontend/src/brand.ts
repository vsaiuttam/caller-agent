/**
 * The product's name and voice, in one place. A rename is a one-file change:
 * everything user-facing that says the name reads it from here (the favicon
 * and <title> in index.html are the only other spots, and they are static).
 */

export const BRAND = {
  name: "Samvaad",
  /** संवाद — "conversation". Shown as a quiet subtitle, never instead of the name. */
  nativeName: "संवाद",
  tagline: "AI voice agents that sound human.",
  description:
    "Design a calling campaign, rehearse it, then watch every conversation happen live — transcripts, outcomes and follow-ups saved for you.",
  /** Used by the agent character's accessible label. */
  agentName: "Samvaad agent",
} as const;
