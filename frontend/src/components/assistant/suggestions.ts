/** Questions worth asking on each console page, most specific path first. */
const BY_PATH: Array<[RegExp, string[]]> = [
  [/^\/app\/campaigns\/(new|[^/]+\/edit)/, [
    "Which model should I pick for Hindi calls?",
    "How is the cost per call worked out?",
    "What does the pre-call heads-up message do?",
    "How do I let the agent book appointments?",
  ]],
  [/^\/app\/campaigns\/[^/]+/, [
    "Why isn't this campaign calling?",
    "What does “waiting for window” mean?",
    "How do retries and attempts work?",
    "How do I add more contacts?",
  ]],
  [/^\/app\/campaigns/, [
    "How do I create my first campaign?",
    "Why isn't my campaign calling?",
    "What's the difference between pause and complete?",
  ]],
  [/^\/app\/calls/, [
    "Why was this call held for review?",
    "What does “Extraction call failed” mean?",
    "How do I export calls to a spreadsheet?",
  ]],
  [/^\/app\/live/, ["What does whisper do?", "Can I take over a live call?", "Why is the agent slow to reply?"]],
  [/^\/app\/test-lab/, ["How do I test a campaign on my own phone?", "What's the difference between a simulation and a test call?"]],
  [/^\/app\/ai-models/, [
    "How do I connect a local model with Ollama?",
    "Which provider is cheapest for long calls?",
    "Why do some models show “price not set”?",
  ]],
  [/^\/app\/integrations/, ["How do I set up Twilio?", "How do I connect my CRM over MCP?", "How do I turn on WhatsApp follow-ups?"]],
  [/^\/app\/templates/, ["Which template fits appointment reminders?", "Can I change a template after starting from it?"]],
  [/^\/app\/settings/, ["How do I invite a teammate?", "How do I lock the console with a password?"]],
  [/^\/app\/suppressions/, ["How does the do-not-call list work?", "Are STOP replies added automatically?"]],
];

const GENERAL = [
  "How do I set up my first campaign?",
  "Which languages can the agent speak?",
  "How much does a call cost?",
  "How do I connect Twilio?",
];

export function suggestionsFor(pathname: string): string[] {
  return BY_PATH.find(([re]) => re.test(pathname))?.[1] ?? GENERAL;
}
