"""Resumable Delta demo account observer, optionally with automatic entries."""
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
from shutil import copyfile
import subprocess
from tempfile import TemporaryDirectory
import time
from .core import Workspace
from .delta_ledger import DeltaCallError, snapshot, atomic_json, campaign_paths


def retryable(error):
    if isinstance(error, BaseExceptionGroup):
        return all(retryable(child) for child in error.exceptions)
    return isinstance(error, (TimeoutError, ConnectionError, DeltaCallError))


def refresh_workbook(export, state):
    try:
        export()
    except (OSError, subprocess.SubprocessError) as error:
        state['workbook_error'] = type(error).__name__
        return False
    state.update(workbook_error=None, workbook_refreshed_at=datetime.now(timezone.utc).isoformat())
    return True


class Trade1Export:
    """Publish only completed exports without blocking the live exit monitor."""
    timeout = 300

    def __init__(self, run, command, root):
        self.run, self.command, self.root = run, command, root
        self.target = Path(command[1]).with_name('trade1.xlsx')
        self.process = self.scratch = None

    def collect(self, state):
        if self.process is None:
            return None
        remaining = max(0, self.expires - time.monotonic())
        if self.process.poll() is None and remaining > 0:
            return None

        def publish():
            try:
                code = self.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                raise
            if code:
                raise subprocess.CalledProcessError(code, self.command)
            (Path(self.scratch.name)/'trade1.xlsx').replace(self.target)

        try:
            return refresh_workbook(publish, state)
        finally:
            self.discard(state)

    def refresh(self, state):
        self.collect(state)
        if self.process is not None:
            return
        try:
            self.scratch = TemporaryDirectory(prefix='export-', dir=self.run)
            for file in ('ledger.json', 'reviews.json'):
                copyfile(self.run/file, Path(self.scratch.name)/file)
            self.process = subprocess.Popen(
                [*self.command, '--snapshot-dir', self.scratch.name],
                cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.expires = time.monotonic() + self.timeout
            state['workbook_export_running'] = True
        except OSError as error:
            self.discard(state)
            state['workbook_error'] = type(error).__name__

    def discard(self, state):
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        if self.scratch is not None:
            self.scratch.cleanup()
        self.process = self.scratch = None
        state['workbook_export_running'] = False


def record_execution(state, execution):
    state['last_execution'] = execution
    if execution.get('weekly_quota'):
        state['last_weekly_quota'] = execution['weekly_quota']
    if execution.get('batch_id'):
        state['last_batch_attempt'] = execution


def seconds_to_exit(rows, now):
    deadlines = [datetime.fromisoformat(row['deadline_at']).timestamp()
                 for row in rows if row.get('deadline_at') and
                 (row['status'] == 'open' or row.get('timer_exposure_open'))]
    return min(deadlines) - now if deadlines else float('inf')


def next_poll_delay(poll_seconds, rows, now):
    # Start a refresh before the deadline to allow for MCP startup and exchange reads.
    return min(poll_seconds, max(1, seconds_to_exit(rows, now) - 10))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    duration = p.add_mutually_exclusive_group()
    duration.add_argument('--duration-seconds',type=int,default=0)
    duration.add_argument('--until-stopped', action='store_true',
                          help='Continue until STOP, the campaign target or a fatal error')
    p.add_argument('--poll-seconds',type=int,default=30)
    p.add_argument('--node',required=True,help='Bundled Node executable')
    p.add_argument('--campaign', choices=('legacy', 'trade1'), default='legacy')
    p.add_argument('--scan-signals', action='store_true')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--execute-demo', action='store_true', help='Submit single-signal orders on india_testnet')
    mode.add_argument('--execute-batch-demo', action='store_true', help='Submit a cohort on india_testnet')
    args=p.parse_args()
    if args.campaign == 'trade1' and args.execute_demo:
        p.error('trade1 execution requires --execute-batch-demo')
    if not 0<=args.duration_seconds<=3600 or not 15<=args.poll_seconds<=300:
        p.error('Duration 0..3600; polling 15..300 seconds')
    root=Path(__file__).resolve().parents[1]
    run, legacy = campaign_paths(root, args.campaign)
    state_path=run/'observer.json'
    builder_name = 'build-trade1.mjs' if args.campaign == 'trade1' else 'build-trade.mjs'
    builder=root/'outputs/01a1df70-6789-76b0-9431-f0c905a7987a'/builder_name
    deadline = float('inf') if args.until_stopped else time.monotonic()+args.duration_seconds
    execute = args.execute_demo or args.execute_batch_demo
    batch = args.execute_batch_demo or (args.campaign == 'trade1' and args.scan_signals)
    command = [args.node, str(builder), '--no-preview']
    background = Trade1Export(run, command, root) if args.campaign == 'trade1' and args.until_stopped else None
    state=dict(running=True,mode='demo_execution' if execute else 'read_only',
               autonomous_entries_enabled=execute,cycles=0,errors=[],consecutive_failures=0,
               started_at=datetime.now(timezone.utc).isoformat(),stop_reason=None)
    with Workspace(legacy).lock('observer'):
        try:
            if state_path.exists():
                previous = json.loads(state_path.read_text(encoding='utf-8'))
                for field in ('last_batch_attempt', 'workbook_refreshed_at', 'last_weekly_quota'):
                    if field in previous:
                        state[field] = previous[field]
            atomic_json(state_path,state)
            while True:
                if background:
                    background.collect(state)
                if (run/'STOP').exists():
                    state['stop_reason']='stop_file';break
                try:
                    data=asyncio.run(asyncio.wait_for(snapshot(root,scan_signals=args.scan_signals,
                        execute_demo=execute, batch_preview=batch,
                        campaign_id=args.campaign),timeout=55))
                except Exception as error:
                    if not retryable(error):
                        raise
                    state['consecutive_failures'] += 1
                    state['errors'] = (state['errors'] + [type(error).__name__])[-20:]
                    state['last_account_error_at'] = datetime.now(timezone.utc).isoformat()
                    atomic_json(state_path,state)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        state['stop_reason'] = 'account_refresh_failed'
                        raise
                    time.sleep(min(args.poll_seconds, remaining,
                                   5 * 2**min(state['consecutive_failures']-1, 5)))
                    continue
                state['consecutive_failures'] = 0
                state.update(cycles=state['cycles']+1,last_success=data['as_of'],
                             open_trades=sum(t['status']=='open' for t in data['trades']),
                             closed_trades=data['review']['closed'],
                             campaign_closed_trades=data.get('campaign', {}).get('completed'))
                if execute:
                    record_execution(state, data['execution'])
                    atomic_json(state_path,state)
                done = execute and data['campaign']['completed'] >= data['limits']['target_closed'] and (
                    args.campaign != 'trade1' or (
                        data['campaign_reviews']['reviewed'] >= 1000
                        and not data['raw']['positions'] and not data['raw']['orders']
                        and not data['raw']['unresolved_entry']
                        and all(row['status'] == 'closed' for row in data['trades'])))
                if background and not done:
                    background.refresh(state)
                elif args.campaign != 'trade1' or seconds_to_exit(data['trades'], time.time()) > 55:
                    if background:
                        background.discard(state)
                    refresh_workbook(lambda: subprocess.run(
                        command, cwd=root, check=True, capture_output=True,
                        timeout=Trade1Export.timeout if args.campaign == 'trade1' else 45), state)
                if execute:
                    if args.campaign != 'trade1' and (data['execution'].get('protection_unconfirmed')
                            or any(t['status']=='open' and not t.get('protection_verified') for t in data['trades'])):
                        state['stop_reason']='protection_unconfirmed';break
                    if done and not state.get('workbook_error'):
                        state['stop_reason']='target_reached';break
                atomic_json(state_path,state)
                if time.monotonic()>=deadline:
                    state['stop_reason']='duration_completed';break
                delay = next_poll_delay(args.poll_seconds, data['trades'], time.time())
                time.sleep(min(delay,max(0,deadline-time.monotonic())))
        except BaseException as exc:
            state['stop_reason']=state['stop_reason'] or 'error'
            state['errors'].append(type(exc).__name__)
            raise
        finally:
            if background:
                background.discard(state)
            state.update(running=False,finished_at=datetime.now(timezone.utc).isoformat())
            atomic_json(state_path,state)
    print(json.dumps(state))


if __name__=='__main__': main()
