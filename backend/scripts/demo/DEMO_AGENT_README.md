# Demo Agent Management Guide

This guide explains how to manage the **Alyx** demo agent deployed on Railway production.

## Overview

The demo agent "Alyx" is configured in `create_demo_agent.py` and runs on Railway production. The agent:
- **Name:** Alyx
- **Voice Provider:** Grok (xAI)
- **Voice:** Eve (energetic, female, US)
- **Capabilities:** web_search, x_search, book_appointment
- **Purpose:** "Try before you buy" demo for The Tribunal platform

## Setup (First Time)

Before using these commands, ensure your Railway service is linked:

```bash
cd backend
railway service
# Select your backend service from the menu
```

Verify the link:
```bash
railway status
# Should show: Service: [your-backend-service-name]
```

## Quick Commands

### Update Demo Agent on Railway
```bash
cd backend
railway run python scripts/create_demo_agent.py
```

### Check Demo Agent Environment Variables
```bash
railway variables | grep DEMO
```

### View Railway Logs (Monitor Agent Activity)
```bash
railway logs
```

### Open Railway Dashboard
```bash
railway open
```

## Interactive Management Tool

For an interactive menu with all options:
```bash
cd backend/scripts
./manage_demo_agent.sh
```

## Common Tasks

### 1. Update Agent Configuration

When you need to change Alyx's system prompt, voice, tools, or any settings:

1. Edit `backend/scripts/create_demo_agent.py`
2. Update the relevant configuration (e.g., `ALYX_SYSTEM_PROMPT`, `voice_id`, `enabled_tools`)
3. Run on Railway:
   ```bash
   railway run python scripts/create_demo_agent.py
   ```
4. Verify in logs:
   ```bash
   railway logs
   ```

### 2. Test Changes Locally First

Before updating production:
```bash
cd backend
uv run python scripts/create_demo_agent.py
```

This updates your local database. Test the agent, then push to Railway.

### 3. Monitor Demo Agent Calls

Watch real-time activity:
```bash
railway logs --filter "Alyx" --follow
```

### 4. Verify Agent is Active

Check agent status via API:
```bash
# Get the agent details
railway run python -c "
import asyncio
from sqlalchemy import select
from app.core.config import settings
from app.models.agent import Agent
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

async def check():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(
            select(Agent).where(Agent.name == 'Alyx')
        )
        agent = result.scalar_one_or_none()
        if agent:
            print(f'Agent ID: {agent.id}')
            print(f'Active: {agent.is_active}')
            print(f'Voice: {agent.voice_provider}/{agent.voice_id}')
            print(f'Tools: {agent.enabled_tools}')
        else:
            print('Agent not found!')
    await engine.dispose()

asyncio.run(check())
"
```

## Configuration Reference

Current demo agent config (from `.env`):
```
DEMO_WORKSPACE_ID=ba0e0e99-c7c9-45ec-9625-567d54d6e9c2
DEMO_AGENT_ID=5bba3103-f3e0-4eb8-bec0-5423bf4051d4
DEMO_FROM_PHONE_NUMBER=+12485309314
```

## Environment Variables Setup

Ensure Railway has these variables set:
```bash
# Check variables
railway variables

# Set if missing (usually already configured)
railway variables set DEMO_WORKSPACE_ID=ba0e0e99-c7c9-45ec-9625-567d54d6e9c2
railway variables set DEMO_AGENT_ID=5bba3103-f3e0-4eb8-bec0-5423bf4051d4
```

## Troubleshooting

### Agent not responding
1. Check if agent is active:
   ```bash
   railway logs --filter "Alyx"
   ```
2. Verify environment variables are set
3. Ensure `is_active=True` in create_demo_agent.py
4. Re-run the create script

### Changes not taking effect
1. Verify you ran the script on Railway, not locally
2. Check Railway logs for errors
3. Restart Railway service:
   ```bash
   railway restart
   ```

### Script fails with database error
1. Check DATABASE_URL is set on Railway:
   ```bash
   railway variables | grep DATABASE_URL
   ```
2. Verify database migration is up to date:
   ```bash
   railway run alembic current
   ```

## Best Practices

1. **Always test locally first** before pushing changes to production
2. **Monitor logs** after updates to ensure agent responds correctly
3. **Keep the system prompt updated** as platform capabilities evolve
4. **Document major changes** in git commit messages
5. **Use the create script** as the single source of truth for agent config

## Related Files

- `backend/scripts/create_demo_agent.py` - Agent configuration and creation script
- `backend/scripts/manage_demo_agent.sh` - Interactive management tool
- `backend/app/models/agent.py` - Agent model definition
- `backend/.env` - Local environment variables (DO NOT commit)
- `backend/railway.toml` - Railway deployment configuration
