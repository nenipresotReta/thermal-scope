"""Failure recovery and concurrent viewers, using only temporary local state."""
import csv
import io
import queue
import sqlite3
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from learning import Ledger
from server import Handler, Scope, Store, csv_text


class ReplySocket:
    def __init__(self, replies):
        self.replies = replies
        self.data = b''

    def settimeout(self, value):
        pass

    def setsockopt(self, *args):
        pass

    def close(self):
        pass

    def sendall(self, request):
        transaction = struct.unpack('>H', request[:2])[0]
        body = next(self.replies)
        self.data = struct.pack('>HHHB', transaction, 0, len(body) + 1, 1) + body

    def recv(self, count):
        result, self.data = self.data[:count], self.data[count:]
        return result


class ReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'scope.db')
        self.scope = Scope(self.store, '127.0.0.1', .1)

    def collect_replies(self, replies):
        responses = iter(replies)
        published = []
        publish = self.scope.publish

        def record(kind, payload):
            published.append((kind, payload))
            publish(kind, payload)
            if kind == 'sample':
                self.scope.stop.set()

        with patch('server.socket.create_connection', side_effect=lambda *_: ReplySocket(responses)), \
                patch.object(self.scope.stop, 'wait', return_value=False), \
                patch.object(self.scope, 'publish', side_effect=record):
            self.scope.collect()
        return published

    @staticmethod
    def good_response():
        return b'\x03\x10' + struct.pack('>ffff', 25, 25, .1, .01)

    def test_truncated_modbus_exception_reconnects(self):
        events = self.collect_replies([b'\x83', self.good_response()])
        errors = [payload for kind, payload in events if kind == 'status']
        self.assertEqual(len(errors), 1)
        self.assertFalse(errors[0]['connected'])
        self.assertIn('Invalid Modbus exception', errors[0]['message'])
        self.assertTrue(self.scope.status()['connected'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM samples').fetchone()[0], 1)

    def test_database_write_failure_reports_and_recovers(self):
        connection = self.store.connect()

        class FailingOnce:
            failed = False

            def __getattr__(self, key):
                return getattr(connection, key)

            def execute(self, sql, *args):
                if sql.startswith('INSERT INTO samples') and not self.failed:
                    self.failed = True
                    raise sqlite3.OperationalError('database is locked')
                return connection.execute(sql, *args)

        with patch.object(self.store, 'connect', return_value=FailingOnce()):
            events = self.collect_replies([self.good_response(), self.good_response()])
        errors = [payload for kind, payload in events if kind == 'status']
        self.assertEqual(len(errors), 1)
        self.assertFalse(errors[0]['connected'])
        self.assertEqual(errors[0]['message'], 'database is locked')
        self.assertTrue(self.scope.status()['connected'])

    def test_sse_consumer_cannot_break_backpressure_disconnect(self):
        class ConsumerRace(queue.Queue):
            def empty(self):
                # A reader removes the last item after the old empty() check.
                result = super().empty()
                if not result:
                    self.get_nowait()
                return result

        slow = ConsumerRace(maxsize=1)
        slow.put_nowait('old event')
        fast = queue.Queue(maxsize=64)
        self.scope.subscribers.update((slow, fast))
        self.scope.publish('sample', {'t': 1, 'temperature': 25})
        self.assertNotIn(slow, self.scope.subscribers)
        self.assertIsNone(slow.get_nowait())
        self.assertIn('"temperature":25', fast.get_nowait())

    def test_session_start_waits_for_device_configuration(self):
        for action in ({'action': 'start'}, {'action': 'start', 'medium': 'WATER'}):
            done = threading.Event()
            errors = []
            self.scope.state['connected'] = True

            def run():
                try:
                    if 'medium' in action:
                        self.scope.calibrate(action)
                    else:
                        self.scope.action(action)
                except Exception as error:
                    errors.append(error)
                finally:
                    done.set()

            with self.scope.config_lock:
                worker = threading.Thread(target=run)
                worker.start()
                self.assertFalse(done.wait(.1))
            worker.join(3)
            self.assertTrue(done.is_set())
            self.assertEqual(errors, [])

    def test_new_device_does_not_score_old_device_predictions(self):
        first = Ledger('device-a')
        second = Ledger('device-b')
        row = {'t': 1000., 'raw': 25., 'temperature': 25., 'd1': 0., 'd2': 0.}
        with self.store.connect() as db:
            first.tick(db, row, [row])
            old = db.execute('SELECT id FROM forecasts WHERE horizon=5').fetchone()[0]
            before = {**row, 't': 1004.9, 'temperature': 80.}
            after = {**before, 't': 1005.1, 'temperature': 82.}
            second.previous = before
            second.tick(db, after, [before, after])
            self.assertIsNone(db.execute('SELECT actual FROM forecasts WHERE id=?', (old,)).fetchone()[0])
            first.previous = before
            first.tick(db, after, [before, after])
            self.assertAlmostEqual(db.execute('SELECT actual FROM forecasts WHERE id=?', (old,)).fetchone()[0], 81.)

    def test_csv_export_sends_bounded_chunks_before_all_rows_are_read(self):
        handler = object.__new__(Handler)
        handler.wfile = io.BytesIO()
        headers = {}
        handler.send_response = lambda status: self.assertEqual(status, 200)
        handler.send_header = lambda key, value: headers.update({key: value})
        handler.end_headers = lambda: None

        def rows():
            yield ('n', 'event')
            for i in range(2000):
                if i == 1000:
                    self.assertGreater(handler.wfile.tell(), 0)
                yield (i, 'x' * 80)

        handler.reply_csv(rows())
        self.assertEqual(headers['Transfer-Encoding'], 'chunked')
        stream = io.BytesIO(handler.wfile.getvalue())
        payload = bytearray()
        chunk_sizes = []
        while True:
            size = int(stream.readline(), 16)
            if not size:
                self.assertEqual(stream.read(), b'\r\n')
                break
            chunk_sizes.append(size)
            payload.extend(stream.read(size))
            self.assertEqual(stream.read(2), b'\r\n')
        self.assertGreater(len(chunk_sizes), 1)
        self.assertLess(max(chunk_sizes), 33000)
        decoded = list(csv.reader(io.StringIO(payload.decode())))
        self.assertEqual(len(decoded), 2001)
        self.assertEqual(decoded[-1], ['1999', 'x' * 80])

    def test_custom_csv_labels_are_literal_not_formulas(self):
        self.assertEqual(csv_text('FC START'), 'FC START')
        for label in ('=1+1', '+1+1', '-1+1', '@SUM(A1:A2)', '  =1+1', '\tdata'):
            self.assertEqual(csv_text(label), "'" + label)


if __name__ == '__main__':
    unittest.main()
