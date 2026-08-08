import argparse
import asyncio
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from os import environ
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

from dotenv import load_dotenv
from pathlib import Path as _Path
load_dotenv(dotenv_path=_Path(__file__).resolve().parent.parent / '.env')

import discord
import seaborn as sns
from discord.ext import commands
from discord.ext.commands.errors import ExtensionFailed
from matplotlib import pyplot as plt

from tle import constants
from tle.util import codeforces_common as cf_common, db, discord_common
from tle.util.gist_backup import GistBackup


def setup() -> None:
    # Make required directories.
    for path in constants.ALL_DIRS:
        os.makedirs(path, exist_ok=True)

    # logging to console and file on daily interval
    logging.basicConfig(
        format='{asctime}:{levelname}:{name}:{message}',
        style='{',
        datefmt='%d-%m-%Y %H:%M:%S',
        level=logging.INFO,
        handlers=[
            logging.StreamHandler(),
            TimedRotatingFileHandler(
                constants.LOG_FILE_PATH, when='D', backupCount=3, utc=True
            ),
        ],
    )

    # matplotlib and seaborn
    plt.rcParams['figure.figsize'] = 7.0, 3.5
    sns.set()
    options = {
        'axes.edgecolor': '#A0A0C5',
        'axes.spines.top': False,
        'axes.spines.right': False,
    }
    sns.set_style('darkgrid', options)


def strtobool(value: str) -> bool:
    """
    Convert a string representation of truth to true (1) or false (0).

    True values are y, yes, t, true, on and 1; false values are n, no, f,
    false, off and 0. Raises ValueError if val is anything else.
    """
    value = value.lower()
    if value in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    if value in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    raise ValueError(f'Invalid truth value {value!r}.')


class TLEContext(commands.Context):
    async def send(self, *args: Any, **kwargs: Any) -> discord.Message:
        if self.interaction is None and 'reference' not in kwargs:
            kwargs['reference'] = self.message
            kwargs.setdefault('mention_author', False)
        return await super().send(*args, **kwargs)


class TLEBot(commands.Bot):
    def __init__(self, nodb: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.nodb: bool = nodb
        self.oauth_server: Any = None
        self.oauth_state_store: Any = None
        self._keep_alive_task: asyncio.Task[None] | None = None
        self._backup_task: asyncio.Task[None] | None = None

    async def get_context(
        self, message: discord.Message, *, cls: type | None = None
    ) -> commands.Context:
        return await super().get_context(message, cls=cls or TLEContext)

    async def setup_hook(self) -> None:
        cogs = [file.stem for file in Path('tle', 'cogs').glob('*.py')]
        for extension in cogs:
            try:
                await self.load_extension(f'tle.cogs.{extension}')
            except ExtensionFailed as exc:
                cause = exc.__cause__
                if isinstance(cause, ModuleNotFoundError):
                    logging.warning(
                        'Skipping extension %s because an optional dependency is missing: %s',
                        extension,
                        cause,
                    )
                    continue
                logging.exception('Failed to load extension %s', extension)
                raise
            except Exception:
                logging.exception('Failed to load extension %s — skipping', extension)
        logging.info(f'Cogs loaded: {", ".join(self.cogs)}')
        await cf_common.initialize(self, self.nodb)
        if constants.OAUTH_CONFIGURED:
            from tle.util.oauth import OAuthServer, OAuthStateStore

            self.oauth_state_store = OAuthStateStore()
            self.oauth_server = OAuthServer(
                self, self.oauth_state_store, constants.OAUTH_SERVER_PORT
            )
            await self.oauth_server.start()
            logging.info('OAuth callback server started')
        else:
            # Start a minimal health-check server so Render gets 200 OK.
            await self._start_health_server(constants.OAUTH_SERVER_PORT)
        await self.tree.sync()
        logging.info('Slash commands synced')

        # Start self-ping task to keep Render/hosting service alive.
        self._keep_alive_task = asyncio.create_task(self._self_ping_loop())
        # Start backup task to periodically upload database to Gist.
        self._backup_task = asyncio.create_task(self._backup_loop())

    async def close(self) -> None:
        if self._keep_alive_task is not None:
            self._keep_alive_task.cancel()
        if self._backup_task is not None:
            self._backup_task.cancel()
        
        # Upload backup one last time before shutting down
        logging.info("Shutting down... Performing final database backup.")
        await GistBackup.upload(constants.USER_DB_FILE_PATH)
        if self.oauth_server is not None:
            await self.oauth_server.stop()
        try:
            user_db = getattr(self, 'user_db', None)
            if user_db is not None:
                await user_db.close()
        except db.DatabaseDisabledError:
            pass
        cf_cache = getattr(self, 'cf_cache', None)
        if cf_cache is not None:
            await cf_cache.conn.close()
        await super().close()

    async def _backup_loop(self) -> None:
        """Periodically upload the database to GitHub Gist."""
        _BACKUP_INTERVAL = 60 * 60  # 1 hour
        await asyncio.sleep(60) # Initial delay to let the bot start properly
        
        while True:
            try:
                logging.info("Running periodic database backup.")
                await GistBackup.upload(constants.USER_DB_FILE_PATH)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in backup loop: {e}")
            await asyncio.sleep(_BACKUP_INTERVAL)

    async def _start_health_server(self, port: int) -> None:
        """Start a minimal HTTP server with only a health-check endpoint."""

        async def _health(_request: web.Request) -> web.Response:
            return web.json_response({'status': 'ok'})

        app = web.Application()
        app.router.add_get('/', _health)
        self._health_runner = web.AppRunner(app)
        await self._health_runner.setup()
        site = web.TCPSite(self._health_runner, '0.0.0.0', port)
        await site.start()
        logging.info('Health-check server listening on port %d', port)

    async def _self_ping_loop(self) -> None:
        """Periodically ping the bot's own health endpoint to prevent
        Render free-tier from spinning down the service after inactivity."""
        _SELF_PING_INTERVAL = 10 * 60  # 10 minutes
        redirect_uri = environ.get('OAUTH_REDIRECT_URI', '')
        if not redirect_uri:
            # No external URL configured; self-ping is unnecessary.
            return

        # Ensure the URL ends with /
        ping_url = redirect_uri.rstrip('/') + '/'
        logging.info('Self-ping enabled: will ping %s every %ds', ping_url, _SELF_PING_INTERVAL)

        await asyncio.sleep(30)  # Initial delay so the server is ready.
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        logging.debug('Self-ping %s -> %d', ping_url, resp.status)
                except Exception as e:
                    logging.warning('Self-ping failed: %s', e)
                await asyncio.sleep(_SELF_PING_INTERVAL)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument('--nodb', action='store_true')
    args = parser.parse_args()

    token = environ.get('BOT_TOKEN')
    if not token:
        logging.error('Token required')
        return

    allow_self_register = environ.get('ALLOW_DUEL_SELF_REGISTER')
    if allow_self_register:
        constants.ALLOW_DUEL_SELF_REGISTER = strtobool(allow_self_register)

    setup()

    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    bot = TLEBot(
        nodb=args.nodb,
        command_prefix=commands.when_mentioned_or(';'),
        intents=intents,
    )

    def no_dm_check(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage('Private messages not permitted.')
        return True

    # Restrict bot usage to inside guild channels only.
    bot.add_check(no_dm_check)

    async def interaction_guild_check(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                'Private messages not permitted.', ephemeral=True
            )
            return False
        return True

    bot.tree.interaction_check = interaction_guild_check

    @bot.event
    @discord_common.once
    async def on_ready() -> None:
        asyncio.create_task(discord_common.presence(bot))

    bot.add_listener(discord_common.bot_error_handler, name='on_command_error')

    bot.run(token, reconnect=True)


if __name__ == '__main__':
    main()

