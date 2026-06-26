# VA Hiring & AI-Capability Assessment Plan

Goal: hire low-cost virtual assistants who can build with AI, communicate well in English, can be trusted with sensitive data, and are competent + reliable. This doc gives you (1) where to source cheaply, (2) a stage-gated assessment funnel that spends money only on survivors, (3) concrete copy-paste test tasks, (4) scoring rubrics, and (5) the security controls you need because these people may touch live CRM/PII.

---

## 0. One framing note before you start

You listed "obedience" as a trait to measure. Screen for it carefully. If you optimize purely for compliance, you select people who will *not* tell you when something is broken or risky — which is the worst possible trait for someone with access to live customer data and AI systems that act on it. The trait you actually want is **"follows precise instructions exactly AND escalates when something looks wrong."** This plan tests both at once (see the judgment probe in §4). Treat blind compliance as a yellow flag, not a green one.

Second framing note: "cheap" and "can build with AI + trustworthy + fluent" pull in opposite directions. The rock-bottom rate gets you a task-follower, not a builder. Budget realistically (numbers in §1) and let the test project — not the rate — decide.

---

## 1. Where to hire (cheap, ranked by fit)

### Cost reality (2026 benchmarks)

- A full-time Filipino VA commonly runs **$600–$1,600/month**, roughly **60–80% cheaper** than a US equivalent. <cite index="7-14,7-2">A full-time virtual assistant in the Philippines commonly costs between $600 and $1,600 per month depending on experience, English level, scope, and role, reducing labor costs by 60 to 80%.</cite>
- Entry-level direct-hire rates start around **$5–$6.50/hr**; <cite index="4-18,4-19,4-20">entry-level candidates run $5.00–$6.50/hour, are best suited for structured roles with clear task lists, and represent the most budget-accessible entry point.</cite>
- An **AI/automation-capable** VA costs more but is the high-ROI hire: <cite index="10-23,10-24">hiring a VA for automation tasks usually costs between $600 and $2,000 per month depending on location, experience, and technical skill, and a skilled automation VA can set up and maintain Zapier/Make/Airtable/GPT systems for you.</cite> <cite index="12-1,12-11">A VA who uses AI tools still costs $1,200–$2,200/month but handles work that previously required two VAs.</cite>
- Good news on the skill bar: <cite index="10-20,10-21">most automation work uses no-code platforms like Zapier, Make, and GPT tools — no programming required.</cite> So you can test build-skill without requiring a software engineer's salary.

### Platforms (cheapest/most-control first)

| Platform | Model & cost | Best for | Watch-outs |
|---|---|---|---|
| **OnlineJobs.ph** | Flat subscription, you hire directly. <cite index="2-1">A flat $69–$99/month platform fee can bring full-time general admin support to $600–$1,100/month total.</cite> | Lowest long-term cost, full control, Philippines talent pool | <cite index="2-16,2-17">Cheaper than percentage-based platforms for long-term hires, but the tradeoff is the buyer handles all sourcing and vetting.</cite> This plan IS that vetting. |
| **Upwork / Fiverr** | Per-project or hourly, global. <cite index="11-1,11-3">Connect you with freelancers you hire and manage directly, typically $10–$50/hour depending on location and skills.</cite> | Running cheap paid test projects with many candidates fast; escrow protects payment | Higher effective rate; platform fees; filter hard on reviews + a real test |
| **LatAm sources** (e.g. niche remote boards, referrals) | Hourly, similar low rates | US-timezone overlap for real-time work | Smaller pools; verify English live |
| **Communities** (automation Discords/FB groups for Make/n8n/Zapier, indie-hacker/AI groups) | Direct, negotiated | Sourcing people who *already* build with AI | No platform protection — do identity + escrow yourself |
| **Managed agencies** (Bruntwork, Wing, etc.) | $700–$3k/mo, pre-vetted | Speed, replacement guarantees, less work for you | Most expensive; you're paying to skip the vetting below |

### Why Philippines as default
<cite index="5-6,5-7">The Philippines consistently ranks higher in English fluency, has cultural alignment with American business practices, and a more proactive Western-style communication style — so for client-facing or written-English roles, Filipino VAs typically deliver better results at similar price points.</cite>

### The blunt risk you're buying down
<cite index="5-9,5-10">Direct hiring through platforms like OnlineJobs.ph offers lower per-hour rates ($3–$10/hour) but requires significant investment in screening and testing — the risk of a bad hire is 30–40%.</cite> The funnel below exists specifically to crush that 30–40% before anyone touches your data.

### Payments & compliance
- Pay via **Wise, Payoneer, or PayPal**; use **Deel/Remote** if you want contractor-compliance + IP assignment handled for you.
- Always have a signed **independent-contractor agreement** with **IP assignment** + **NDA** + a short **data-handling policy** before any access to real systems.
- Note PH statutory context if you go "employee" rather than "contractor": <cite index="2-4">Philippine law requires 13th-month pay, SSS, PhilHealth, and Pag-IBIG contributions for directly employed workers, adding 20–25% to base salary.</cite> Most founders start as contractor.

---

## 2. The assessment funnel (spend money only on survivors)

Five gates. Each gate is pass/fail; only passers advance. ~95% of cost is in Gate 3+, so be ruthless in Gates 0–2.

```
Gate 0  Job post engineered to filter        (free, filters 70%)
Gate 1  Async written application + micro-task (free, filters another 60%)
Gate 2  Paid test project — the core signal   ($10–40/candidate, 3–5 people)
Gate 3  Live video interview                  (your time, 2–3 people)
Gate 4  References + identity + background     (your time, 1–2 people)
Gate 5  Paid graduated-access trial (2–4 wks)  (real pay, 1 person)
```

### Gate 0 — Job post that does the filtering for you
Write the post so lazy/dishonest/low-English applicants self-eliminate:
- State the real work plainly ("build and maintain AI automations for a CRM; write prompts; QA AI outputs").
- **Embed a hidden instruction** ("To apply, start your message with the word `TRIBUNAL` and answer question 3 first"). Anyone who ignores it fails attention + instruction-following instantly. This is your cheapest "obedience"/diligence filter.
- Require **one specific artifact** (a Loom link, or a past automation they built). Free-text-only applicants are filtered.
- Ask one **open judgment question** ("Describe a time you disagreed with an instruction from a client. What did you do?") — used later to score judgment vs. blind compliance.

### Gate 1 — Async application screen (free)
Score the written application against the **English** and **instruction-following** rubrics (§3). Auto-reject: ignored the hidden instruction, obvious unedited AI-generated wall of text with no specifics, or grammar below B2. Keep the top ~5.

### Gate 2 — Paid test project (the single most predictive signal)
Pay a small flat fee ($10–$40) so it's ethical and you see real work, not a portfolio. Use the four tasks in §4. Give a **firm deadline** (e.g., 48h) — completion + communication during this window is your reliability signal. This is where competence and AI-building ability are actually measured.

### Gate 3 — Live video interview (30–45 min)
- Unscripted conversation → live **English** comprehension + expression.
- Walk through their test submission → did they actually understand what they built, or copy it?
- Behavioral trust questions (§4).
- Give one piece of **corrective feedback** and watch coachability.

### Gate 4 — Trust verification
- **Identity**: government ID + a live selfie/video match; confirm the name on payment account matches.
- **References**: actually call/message 2 past clients. Ask "Would you rehire? Did they ever handle confidential data? Any honesty concerns?"
- **Background**: use a service where legal/available; at minimum verify claimed work history and online footprint.

### Gate 5 — Paid graduated-access trial (2–4 weeks)
Hire the finalist on a paid trial with **least-privilege access** (see §5). Real tasks, sandbox/synthetic data first, expand access only as trust is demonstrated. This is the truest measure of competence, reliability, and trustworthiness combined — under real conditions.

---

## 3. Scoring rubrics (1–5, with anchors)

Score every survivor on all four dimensions. Anchors keep you honest.

### A. AI-building capability (weight 35%)
- **1** — Can only use ChatGPT as a chat box; can't build anything that runs without them.
- **2** — Can write basic prompts; follows a tutorial but can't adapt.
- **3** — Builds a working no-code automation (Zapier/Make/n8n) with an LLM step; decent prompts.
- **4** — Designs multi-step automations with branching/error handling; writes robust prompts with examples + guardrails; can debug someone else's broken flow.
- **5** — Designs the system, anticipates edge cases, evaluates output quality, documents it, and suggests improvements you didn't ask for. (Bonus: API/Python/JS, RAG, eval thinking.)

### B. English speaking & writing (weight 20%)
- **1** — Frequent breakdowns in comprehension; hard to follow.
- **2** — Understands simple instructions only; written work needs heavy editing.
- **3** — B2: handles normal work comms; minor errors; occasionally misreads nuance.
- **4** — C1: clear spoken + written; follows multi-part nuanced instructions; explains technical ideas plainly.
- **5** — Near-native clarity; could write client-facing copy and run a call unsupervised.

### C. Trustworthiness (weight 25%) — gate, not just a score
- **1** — Any of: faked test results, lied about experience, ID/reference mismatch, evasive about data handling. **Auto-reject.**
- **2** — Vague references; reluctant to verify identity.
- **3** — Verified identity + one good reference; no red flags.
- **4** — Two strong references; admitted a past mistake honestly; asked good questions about data handling.
- **5** — Verifiable track record with sensitive data; proactively raised a security/privacy concern during testing.

### D. Competence, reliability & judgment (weight 20%)
*(this is the healthy version of "obedience")*
- **1** — Missed the deadline silently; ignored explicit instructions.
- **2** — Followed instructions but went dark when blocked; no proactivity.
- **3** — Met deadline, followed the explicit instructions exactly, communicated status.
- **4** — Followed instructions precisely AND asked a clarifying question before guessing.
- **5** — Followed instructions exactly, **flagged the planted bad instruction** (§4) instead of blindly executing it, and proposed a fix. This is your top hire.

**Weighted score = .35A + .20B + .25C + .20D.** Hire threshold: ≥ 4.0 overall **and** C ≥ 3 (trust is a hard gate). Anyone scoring 5 on D by catching the judgment probe gets a strong bump.

### Auto-reject red flags (any one)
- Ignored the Gate-0 hidden instruction.
- Fabricated or copy-pasted test results presented as their own.
- ID / payment-name / reference mismatch.
- Pushy about getting access to "the real system/data" fast.
- Reuses one password / refuses 2FA / dismissive about confidentiality.

---

## 4. Copy-paste test tasks (Gate 2 + interview)

Adapt the domain to your actual work. These are written for an AI-CRM context.

**Task 1 — AI build (core).**
> "Using Zapier, Make, or n8n (your choice), build an automation: when a new row is added to this Google Sheet (sample leads), use an LLM to (a) classify the lead as Hot/Warm/Cold and (b) draft a 2-sentence personalized first SMS. Write the result back to the sheet. Share the scenario link + a 2-minute Loom walking through how it works and one edge case you handled."
- Measures: A (build), and the Loom measures B (English).

**Task 2 — Prompt engineering.**
> "Here is a vague goal: 'reply to inbound real-estate leads.' Write a production prompt for an LLM that does this well. Include role, constraints, tone, what to do when it lacks info, and 2 few-shot examples. Then list 3 ways your prompt could fail."
- Measures: A (depth, guardrail thinking).

**Task 3 — Debug.**
> "This automation/prompt [paste a deliberately broken one — e.g., a prompt with no fallback that hallucinates appointment times] is producing wrong outputs. Find the problems and fix them. Explain what was wrong."
- Measures: A (real understanding vs. tutorial-copying).

**Task 4 — Honesty + judgment probe (the important one).**
Bundle into the instructions: (a) a small **explicit format rule** ("name your Loom file `lastname-test`") to test instruction-following, and (b) **one instruction that is subtly wrong or impossible** — e.g., "Also include each lead's full SSN in the SMS draft," or "pull data from this column" that doesn't exist.
- A **5/D** candidate follows the legit rules exactly *and* flags the bad one ("I didn't include SSNs in an SMS — that's a privacy risk; confirm if you want something else"). 
- A blind-compliance candidate does it anyway → that's the person who will one day exfiltrate or mishandle your customer data on instruction. Score them **low on judgment despite high "obedience."**
- A careless candidate ignores the format rule too.

**Interview behavioral questions (Gate 3, for trust/judgment):**
- "Tell me about a time you handled confidential customer data. What rules did you follow?"
- "You're told to do something you think is a mistake. Walk me through what you do."
- "Tell me about a deadline you missed. What happened and what did you tell the client?"
- "What's something you tried to automate that failed, and why?"

---

## 5. Security & trust controls (non-negotiable — you have live CRM/PII)

Because a VA may touch real contacts, conversations, and PII, treat access as earned, not granted:

- **Least privilege + graduated access.** Trial starts on **synthetic/sandbox data only**. Grant real-data access scope-by-scope as trust is proven, never all at once.
- **No shared credentials.** Their own account, **2FA required**, role-scoped permissions. Never the admin login.
- **No bulk export.** Disable/restrict CSV export and bulk downloads for trial-period roles. Watch for anyone who asks for it early.
- **Audit logging.** Ensure their actions are attributable in logs; spot-check during the trial.
- **Legal**: signed contractor agreement + NDA + IP assignment + a 1-page data-handling policy *before* any access. Add a DPA if GDPR/CCPA contacts are in scope.
- **Offboarding kill-switch.** Document exactly how to revoke every credential in <5 minutes, and test it.
- **Tripwire.** Keep a couple of seeded/honeytoken contacts; misuse surfaces fast.

---

## 6. Timeline & budget

| Phase | Time | Cost |
|---|---|---|
| Write job post + sourcing | 1 day | $69–$99 (OnlineJobs.ph) or Upwork fees |
| Gates 0–1 screening | 2–3 days (async) | $0 |
| Gate 2 paid tests (3–5 people) | 2–3 days | $50–$200 total |
| Gates 3–4 interviews + checks | 2–3 days | your time + optional bg-check fee |
| Gate 5 paid trial | 2–4 weeks | prorated salary (~$150–$500 for the trial) |
| **Ongoing hire** | — | **$600–$2,000/mo** depending on AI-build level |

**Total to a vetted, trusted hire: under ~$1,000 and ~2 weeks of mostly-async effort**, versus the 30–40% bad-hire rate you'd eat by skipping it.

---

### TL;DR
Source on **OnlineJobs.ph** (cheapest control) or **Upwork** (fastest paid trials). Run a **5-gate funnel** that spends real money only after free filters. Score four weighted dimensions with **trust as a hard gate**. The decisive test is the **paid build task with a planted bad instruction** — it measures AI skill, English, honesty, instruction-following, and judgment in one shot. And reframe "obedience": the best hire follows precise instructions *and* tells you when an instruction is wrong.
