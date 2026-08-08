import base64
import logging
from pathlib import Path

import aiohttp

from tle import constants

logger = logging.getLogger(__name__)


class GistBackup:
    @staticmethod
    async def download(db_path: Path) -> bool:
        """
        Download database from Gist and write it to db_path.
        Returns True if successful.
        """
        if not constants.GIST_TOKEN or not constants.GIST_ID:
            logger.warning(
                'GIST_TOKEN or GIST_ID not provided. Skipping backup download.'
            )
            return False

        url = f'https://api.github.com/gists/{constants.GIST_ID}'
        headers = {
            'Authorization': f'token {constants.GIST_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        files = data.get('files', {})
                        if 'user.db' in files:
                            content = files['user.db']['content']
                            if content:
                                # Decode from base64
                                decoded = base64.b64decode(content)
                                # Make sure the parent directory exists
                                db_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(db_path, 'wb') as f:
                                    f.write(decoded)
                                logger.info(
                                    'Successfully downloaded database from Gist.'
                                )
                                return True
                    else:
                        logger.warning(
                            f'Failed to fetch Gist: {resp.status} - {await resp.text()}'
                        )
        except Exception as e:
            logger.exception(f'Error downloading backup from Gist: {e}')

        return False

    @staticmethod
    async def upload(db_path: Path) -> bool:
        """Read database from db_path and upload to Gist. Returns True if successful."""
        if not constants.GIST_TOKEN or not constants.GIST_ID:
            logger.warning(
                'GIST_TOKEN or GIST_ID not provided. Skipping backup upload.'
            )
            return False

        if not db_path.exists():
            logger.warning(f'Database file {db_path} does not exist to upload.')
            return False

        url = f'https://api.github.com/gists/{constants.GIST_ID}'
        headers = {
            'Authorization': f'token {constants.GIST_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
        }

        try:
            with open(db_path, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')

            payload = {'files': {'user.db': {'content': content}}}

            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        logger.info('Successfully uploaded database backup to Gist.')
                        return True
                    else:
                        logger.warning(
                            f'Failed to update Gist: {resp.status} - '
                            f'{await resp.text()}'
                        )
        except Exception as e:
            logger.exception(f'Error uploading backup to Gist: {e}')

        return False
