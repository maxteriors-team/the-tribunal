# Demo Agent Quick Reference

## Setup (First Time Only)

Link Railway service:
```bash
cd backend && railway service
# Select your backend service from the list
```

## One-Line Commands

### Update demo agent on Railway
```bash
cd backend/scripts && ./update-demo-agent.sh
```

### View Railway logs
```bash
cd backend && railway logs
```

### Interactive management menu
```bash
cd backend/scripts && ./manage_demo_agent.sh
```

## What is the Demo Agent?

**Name:** Alyx
**Location:** `backend/scripts/create_demo_agent.py`
**Purpose:** Public-facing demo voice agent for The Tribunal
**Deployment:** Railway production environment

## When to Update

Update the demo agent when you need to:
- Change Alyx's system prompt or personality
- Enable/disable tools (web_search, x_search, book_appointment)
- Switch voice provider or voice ID
- Update booking integration (Cal.com event type)
- Modify agent capabilities or behavior

## Workflow

1. **Edit** `backend/scripts/create_demo_agent.py`
2. **Test locally** (optional): `cd backend && uv run python scripts/create_demo_agent.py`
3. **Deploy to Railway**: `cd backend/scripts && ./update-demo-agent.sh`
4. **Verify**: `cd backend && railway logs`

## Files

| File | Purpose |
|------|---------|
| `backend/scripts/create_demo_agent.py` | Agent configuration & creation |
| `backend/scripts/update-demo-agent.sh` | Quick one-line deploy script |
| `backend/scripts/manage_demo_agent.sh` | Interactive management menu |
| `backend/scripts/DEMO_AGENT_README.md` | Detailed documentation |

## Environment Variables

```bash
DEMO_WORKSPACE_ID='<workspace UUID>'
DEMO_AGENT_ID='<active demo-agent UUID>'
DEMO_FROM_PHONE_NUMBER='<dedicated demo number>'
```

Set explicit demo resources on Railway before enabling the demo.

## Troubleshooting

**Agent not responding?**
```bash
cd backend && railway logs --filter "Alyx"
```

**Need to restart Railway?**
```bash
cd backend && railway restart
```

**Check agent configuration?**
```bash
cd backend && railway run python -c "from app.models.agent import Agent; import asyncio; asyncio.run(check_agent())"
```

## Support

- Full docs: `backend/scripts/DEMO_AGENT_README.md`
- Railway dashboard: `railway open`
- Project: aicrm-backend (production)
