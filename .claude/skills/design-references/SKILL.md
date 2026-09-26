---
name: design-references
description: Reference DESIGN.md files from VoltAgent's awesome-claude-design / awesome-design-md collection (ElevenLabs, Intercom), used as inspiration when designing or restyling Samvaad's UI — landing pages, login, console chrome, colour and typography decisions. Use together with frontend/DESIGN.md, which is Samvaad's own source of truth.
---

# Design references (awesome-claude-design)

Two `DESIGN.md` files from the MIT-licensed
[awesome-design-md](https://github.com/VoltAgent/awesome-design-md) collection
(indexed by [awesome-claude-design](https://github.com/VoltAgent/awesome-claude-design)).
Each describes a product's visual language as tokens, rules and rationale.

| File | Why it's here |
| --- | --- |
| `references/elevenlabs.DESIGN.md` | A premium voice-AI product: restraint, monochrome surfaces, confident type, sound as a visual motif. Closest in domain to Samvaad. |
| `references/intercom.DESIGN.md` | A conversational SaaS: warm, human, message-shaped UI, and a clear line from marketing site into product. |

## How to use them

1. Read `frontend/DESIGN.md` first. It is Samvaad's own design system and
   always wins. If it doesn't exist yet, write it before building UI.
2. Read these references for **principles**: how they pair type, space colour,
   pace motion, lead from a landing page into the product, and handle trust
   and density. Then decide what fits Samvaad and write the decision into
   `frontend/DESIGN.md` with its rationale.
3. **Never copy identity.** Don't reuse these companies' names, logos, taglines,
   illustrations, exact colour values or copy, and don't make Samvaad look like
   either product. Samvaad keeps its own brand (see `frontend/src/brand.ts`).
