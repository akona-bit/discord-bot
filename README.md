# Discord Bot Deployment

This bot is ready to deploy to Render as a background worker for 24/7 uptime.

## Local setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a `.env` file with your Discord token:
   ```env
   DISCORD_TOKEN=your-bot-token-here
   ```
3. Run locally:
   ```bash
   python main.py
   ```

## Deploy on Render
1. Push this repository to GitHub.
2. Create a new Render service of type **Worker**.
3. Connect the service to the repository and the branch containing this code.
4. Use the default build command:
   ```bash
   pip install -r requirements.txt
   ```
5. Use this start command:
   ```bash
   python main.py
   ```
6. Add a secret environment variable on Render:
   - `DISCORD_TOKEN`
7. Deploy the service.

Once deployed, Render will keep the worker running automatically and your bot stays online as long as the service is active.
