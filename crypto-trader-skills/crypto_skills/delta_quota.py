"""Read and enforce the signed-in Codex account's weekly allowance."""

import asyncio
import json
import math
import os
import subprocess
import time


def assess_weekly_quota(data, *, now):
    limits = (data.get('rateLimitsByLimitId') or {}).get('codex') or data.get('rateLimits')
    weekly = []
    for key in ('primary', 'secondary'):
        window = (limits or {}).get(key)
        if not window or window.get('windowDurationMins') != 10080:
            continue
        used = window.get('usedPercent')
        reset = window.get('resetsAt')
        if (type(used) not in (int, float) or not 0 <= used <= 100
                or type(reset) not in (int, float) or not math.isfinite(reset) or reset <= now):
            return {'status': 'weekly_quota_unavailable'}
        weekly.append((used, reset))
    if len(weekly) != 1:
        return {'status': 'weekly_quota_unavailable'}
    used, reset = weekly[0]
    remaining = 100 - used
    return {'status': 'weekly_quota_reserve' if remaining <= 50 else 'available',
            'remaining_percent': remaining, 'resets_at': reset}


def quota_allows_entry(quota, *, now):
    return (quota['status'] == 'available' and now < quota['resets_at']
            and 0 <= now - quota['checked_at'] < 60)


def entry_hold_reason(run):
    if (run / 'STOP').exists():
        return 'stop_file'
    if (run / 'ENTRY_HOLD').exists():
        return 'entry_hold'
    return None


async def read_weekly_quota():
    """Read only the usage window. Discard credentials, account data and server logs."""
    process = None
    try:
        async with asyncio.timeout(10):
            process = await asyncio.create_subprocess_exec(
                os.environ.get('CODEX_APP_RUNTIME_CLI_PATH') or 'codex', 'app-server',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

            async def send(**message):
                process.stdin.write((json.dumps(message) + '\n').encode('utf-8'))
                await process.stdin.drain()

            async def result(request_id):
                while line := await process.stdout.readline():
                    response = json.loads(line)
                    if response.get('id') == request_id:
                        return response['result']
                raise ConnectionError('Codex app server closed')

            await send(id=1, method='initialize',
                       params={'clientInfo': {'name': 'delta-demo', 'version': '1.0'}})
            await result(1)
            await send(method='initialized', params={})
            await send(id=2, method='account/rateLimits/read')
            data = await result(2)
        now = time.time()
        return dict(assess_weekly_quota(data, now=now), checked_at=now)
    except (OSError, TimeoutError, ValueError, KeyError, TypeError, AttributeError):
        return {'status': 'weekly_quota_unavailable'}
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
