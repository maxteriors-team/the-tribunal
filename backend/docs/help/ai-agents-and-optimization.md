---
title: AI Agents, Practice, Knowledge, Suggestions, and Experiments
slug: ai-agents-optimization
tags:
  - agents
  - roleplay
  - knowledge base
  - suggestions
  - experiments
  - prompts
---

# AI Agents, Practice, Knowledge, Suggestions, and Experiments

## Create and configure an AI Agent

Route: `/agents`. Sidebar label: **AI Agents**.

1. Open **AI Agents** and select **Create Agent** to open `/agents/create`.
2. Configure the voice agent's supported identity, prompt, voice, booking, and communications settings.
3. Select **Create Agent**, then open `/agents/{agent_id}` to manage the saved agent.
4. Assign agents to campaigns or communications only after testing the intended behavior.

An agent's prompt and knowledge affect customer conversations. Review changes before assigning the agent to live outreach.

## Practice with roleplay

Route: `/agents/practice`. Sidebar label: **Practice / Roleplay**.

Start a roleplay session, choose the available scenario and agent, complete the simulated conversation, then review the score and feedback. Practice runs do not contact a real lead. Use them before launching a changed prompt or sales approach.

## Add agent Knowledge Base documents

Route: `/knowledge`. Sidebar label: **Knowledge Base**. An agent's detail page also has a Knowledge Base tab.

1. Open the target agent and its **Knowledge Base** tab.
2. Select **Add Document**.
3. Enter a title, document type, priority, and content.
4. Select **Add Document** and check the token-usage meter.
5. Delete an obsolete document only after confirming the agent no longer needs it.

This is customer-conversation knowledge for an AI agent. It is separate from the CRM Assistant's built-in product-help articles.

## Review AI Suggestions

Route: `/suggestions`. Sidebar label: **AI Suggestions**.

Use **Improve with AI** on an agent to generate prompt-improvement suggestions from performance signals. On the suggestions screen, review the evidence and proposed change; then approve or reject it with the available controls. Do not describe a suggestion as live until its status shows that it was applied.

## Run Experiments

Route: `/experiments`. Sidebar label: **Experiments**.

Create an experiment at `/experiments/new` to compare supported prompt or agent variants, configure its audience and success measure, then start it only when the variants and traffic rules are ready. Open `/experiments/{experiment_id}` to monitor recorded results before selecting or rolling out a winner. Experiments require enough live data to support a meaningful comparison.
