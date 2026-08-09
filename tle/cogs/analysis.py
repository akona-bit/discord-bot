import io
import logging
import random
from collections import defaultdict
from typing import Any

import discord
import numpy as np
from discord.ext import commands
from matplotlib import pyplot as plt

from tle.util import codeforces_api as cf, discord_common

logger = logging.getLogger(__name__)

# The most common Codeforces tags to focus on
MAIN_TAGS = [
    'dp',
    'math',
    'graphs',
    'greedy',
    'data structures',
    'implementation',
    'brute force',
    'constructive algorithms',
    'sortings',
    'binary search',
    'strings',
    'number theory',
    'geometry',
    'trees',
    'combinatorics',
    'two pointers',
]


class Analysis(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_ac_submissions(self, handle: str) -> list[Any]:
        try:
            subs = await cf.user.status(handle=handle)
            return [sub for sub in subs if sub.verdict == 'OK']
        except Exception as e:
            logger.warning(f'Error fetching status for {handle}: {e}')
            return []

    def _get_tag_stats(self, ac_subs: list[Any]) -> dict[str, int]:
        tag_counts = defaultdict(int)
        solved_problems = set()
        for sub in ac_subs:
            prob_id = f'{sub.problem.contestId}{sub.problem.index}'
            if prob_id not in solved_problems:
                solved_problems.add(prob_id)
                for tag in sub.problem.tags:
                    tag_counts[tag] += 1
        return tag_counts

    @commands.command(brief='Phân tích điểm mạnh/yếu theo tag', usage='[handle]')
    async def tags(self, ctx: commands.Context, handle: str = None) -> None:
        """Hiển thị biểu đồ Radar phân tích các dạng bài đã giải (Tags)."""
        if not handle:
            user_id = ctx.author.id
            handle = await self.bot.user_db.get_handle(user_id, ctx.guild.id)
            if not handle:
                await ctx.send(
                    embed=discord_common.embed_alert('Bạn chưa liên kết handle!')
                )
                return

        msg = await ctx.send(f'Đang phân tích tags cho **{handle}**...')

        ac_subs = await self._get_ac_submissions(handle)
        if not ac_subs:
            await msg.edit(content=f'{handle} chưa giải được bài nào!')
            return

        tag_counts = self._get_tag_stats(ac_subs)

        # Filter to MAIN_TAGS to avoid clutter, take top 8 user's tags among main ones
        filtered_tags = {t: tag_counts.get(t, 0) for t in MAIN_TAGS}
        # Sort by count desc and take top 8
        sorted_tags = sorted(filtered_tags.items(), key=lambda x: x[1], reverse=True)[
            :8
        ]

        if not sorted_tags or sorted_tags[0][1] == 0:
            await msg.edit(content=f'{handle} chưa giải bài nào thuộc các tag cơ bản.')
            return

        labels = [t[0].title() for t in sorted_tags]
        values = [t[1] for t in sorted_tags]

        # Close the loop for radar chart
        labels.append(labels[0])
        values.append(values[0])

        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles[-1] = angles[0]  # Close loop

        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
        ax.plot(angles, values, color='#1f77b4', linewidth=2)
        ax.fill(angles, values, color='#1f77b4', alpha=0.25)

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_thetagrids(np.degrees(angles[:-1]), labels[:-1])

        # Remove y-tick labels
        ax.set_yticklabels([])

        plt.title(f'Tag Analysis: {handle}', size=16, y=1.1)

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', transparent=True)
        buf.seek(0)
        plt.close(fig)

        file = discord.File(buf, filename='tags.png')
        embed = discord.Embed(
            title=f'Phân tích Tag của {handle}', color=discord_common._SUCCESS_GREEN
        )
        embed.set_image(url='attachment://tags.png')
        embed.set_footer(text=f'Dựa trên {len(ac_subs)} bài nộp Accepted.')

        await msg.delete()
        await ctx.send(file=file, embed=embed)

    @commands.command(brief='Gợi ý bài tập theo tag yếu nhất', usage='[handle]')
    async def recommend(self, ctx: commands.Context, handle: str = None) -> None:
        """Gợi ý 1 bài tập thuộc dạng bạn yếu nhất ở mức rating phù hợp."""
        if not handle:
            user_id = ctx.author.id
            handle = await self.bot.user_db.get_handle(user_id, ctx.guild.id)
            if not handle:
                await ctx.send(
                    embed=discord_common.embed_alert('Bạn chưa liên kết handle!')
                )
                return

        msg = await ctx.send(f'Đang tìm bài phù hợp cho **{handle}**...')

        try:
            user = await self.bot.user_db.fetch_cf_user(handle)
        except Exception:
            await msg.edit(content='Không tìm thấy user.')
            return

        target_rating = 1000
        if user.rating:
            # Recommend a problem slightly above current rating
            target_rating = round((user.rating + 100) / 100) * 100

        ac_subs = await self._get_ac_submissions(handle)
        tag_counts = self._get_tag_stats(ac_subs)

        solved_problem_names = set()
        for sub in ac_subs:
            solved_problem_names.add(sub.problem.name)

        # Find weakest tag among MAIN_TAGS (least solved)
        # But we only want tags they have at least *tried* or are common.
        # Let's just pick from MAIN_TAGS, sort ascending by count.
        weakest_tags = sorted(MAIN_TAGS, key=lambda t: tag_counts.get(t, 0))

        problem_found = None
        weak_tag = None

        # Try to find a problem in the weakest tags
        for tag in weakest_tags:
            available_problems = [
                prob
                for prob in self.bot.cf_cache.problem_cache.problems
                if prob.rating == target_rating
                and tag in prob.tags
                and prob.name not in solved_problem_names
            ]
            if available_problems:
                problem_found = random.choice(available_problems)
                weak_tag = tag
                break

        if not problem_found:
            # Fallback to any rating if exact match not found
            for tag in weakest_tags:
                available_problems = [
                    prob
                    for prob in self.bot.cf_cache.problem_cache.problems
                    if tag in prob.tags and prob.name not in solved_problem_names
                ]
                if available_problems:
                    # Pick closest rating
                    available_problems.sort(
                        key=lambda p: abs((p.rating or 0) - target_rating)
                    )
                    problem_found = available_problems[0]
                    weak_tag = tag
                    break

        if not problem_found:
            await msg.edit(
                content='Không thể tìm thấy bài phù hợp! Bạn đã giải hết bài trên Codeforces? 🤯'  # noqa: E501
            )
            return

        embed = discord.Embed(
            title=f'Gợi ý bài tập cho {handle}',
            url=f'https://codeforces.com/contest/{problem_found.contestId}/problem/{problem_found.index}',  # noqa: E501
            color=cf.rating2rank(problem_found.rating).color_embed
            if problem_found.rating
            else discord_common._SUCCESS_GREEN,
            description=f'Có vẻ bạn cần luyện tập thêm phần **{weak_tag.upper()}**.\n'
            f'Bạn đã giải {tag_counts.get(weak_tag, 0)} bài thuộc tag này.',
        )
        embed.add_field(
            name='Bài tập',
            value=f'{problem_found.index}. {problem_found.name}',
            inline=False,
        )
        embed.add_field(name='Rating', value=str(problem_found.rating), inline=True)
        if problem_found.tags:
            embed.add_field(
                name='Tags', value=', '.join(problem_found.tags), inline=True
            )

        await msg.delete()
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Analysis(bot))
