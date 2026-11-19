import subprocess
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from crypto_skills import delta_observer
from crypto_skills.delta_observer import record_execution, refresh_workbook, retryable


class DeltaObserverTests(unittest.TestCase):
    def test_trade1_export_uses_one_stable_snapshot_while_polling_continues(self):
        state = {}
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run/'ledger.json').write_text('first ledger')
            (run/'reviews.json').write_text('first reviews')
            process = Mock()
            process.poll.return_value = None
            with patch.object(delta_observer.subprocess, 'Popen', return_value=process) as popen:
                export = delta_observer.Trade1Export(run, ['node', str(run/'builder')], run)
                export.refresh(state)
                export.refresh(state)
                self.assertEqual(popen.call_count, 1)
                copy = Path(popen.call_args.args[0][-1])
                (run/'ledger.json').write_text('second ledger')
                self.assertEqual((copy/'ledger.json').read_text(), 'first ledger')
                self.assertTrue(state['workbook_export_running'])
                process.wait.assert_not_called()
                process.poll.return_value = 0
                process.wait.return_value = 0
                (copy/'trade1.xlsx').write_bytes(b'complete')
                export.collect(state)
                self.assertFalse(state['workbook_export_running'])
                self.assertIsNone(state['workbook_error'])
                self.assertFalse(copy.exists())
                self.assertEqual((run/'trade1.xlsx').read_bytes(), b'complete')

    def test_later_idle_cycles_preserve_batch_stop_details(self):
        state = {}
        attempted = dict(status='batch_attempted', batch_id='demo-1', full_lots=1,
                         stop_detail='Quote expired before submission')
        record_execution(state, attempted)
        record_execution(state, {'status':'account_blocked'})
        self.assertEqual(state['last_execution']['status'], 'account_blocked')
        self.assertEqual(state['last_batch_attempt'], attempted)

    def test_continuous_observer_recovers_then_obeys_stop_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / 'runs/delta-demo-loop/observer.json'
            account = dict(as_of='account-time', trades=[], review={'closed':0})
            snapshot = AsyncMock(side_effect=[TimeoutError(), account])

            def export(*args, **kwargs):
                (state_path.parent/'STOP').touch()
                raise subprocess.CalledProcessError(1, ['node'])

            with (patch.object(delta_observer, '__file__', str(root/'crypto_skills/delta_observer.py')),
                  patch.object(delta_observer, 'snapshot', snapshot),
                  patch.object(delta_observer.subprocess, 'run', side_effect=export),
                  patch.object(delta_observer.time, 'sleep'),
                  patch('sys.argv', ['observer','--node','node','--until-stopped']),
                  patch('builtins.print')):
                delta_observer.main()
            state = json.loads(state_path.read_text())
            self.assertEqual(snapshot.await_count, 2)
            self.assertEqual(state['cycles'], 1)
            self.assertEqual(state['errors'], ['TimeoutError'])
            self.assertEqual(state['stop_reason'], 'stop_file')
            self.assertFalse(state['running'])
            self.assertEqual(state['workbook_error'], 'CalledProcessError')

    def test_transport_timeout_in_exception_group_is_retryable(self):
        self.assertTrue(retryable(ExceptionGroup('MCP session', [TimeoutError()])))
        self.assertFalse(retryable(ExceptionGroup('MCP session', [ValueError()])))
        self.assertFalse(retryable(ExceptionGroup('mixed', [TimeoutError(), ValueError()])))

    def test_export_failure_is_recorded_separately_from_account_cycle(self):
        def locked():
            raise subprocess.CalledProcessError(1, ['node'])
        state = {'cycles':3, 'last_success':'account-time'}
        self.assertFalse(refresh_workbook(locked, state))
        self.assertEqual(state['last_success'], 'account-time')
        self.assertEqual(state['workbook_error'], 'CalledProcessError')
        self.assertTrue(refresh_workbook(lambda:None, state))
        self.assertIsNone(state['workbook_error'])
