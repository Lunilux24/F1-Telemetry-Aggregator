import os
import unittest
from unittest.mock import patch, MagicMock

os.environ["F1_S3_BUCKET"] = "test-bucket"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["JOLPICA_URL"] = "http://test.api.url"

import ingest.fastf1_ingest as ingest

class TestIngestJob(unittest.TestCase):
    @patch('ingest.fastf1_ingest.requests.Session')
    def test_fetch_jolpica(self, mock_session):
        mock_sess = MagicMock()
        mock_session.return_value = mock_sess
        mock_resp = MagicMock()
        mock_resp.content = b'{"test": 1}'
        mock_resp.raise_for_status = MagicMock()
        mock_sess.get.return_value = mock_resp
        result = ingest.fetch_jolpica(mock_sess, 'http://fake.url')
        self.assertEqual(result, b'{"test": 1}')

    @patch('ingest.fastf1_ingest.boto3.client')
    def test_write_to_s3(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        ingest.write_to_s3('bucket', 'key', b'body', region='us-east-1', metadata={'foo': 'bar'})
        mock_s3.put_object.assert_called_once()

    @patch('ingest.fastf1_ingest.fastf1.Cache.enable_cache')
    @patch('ingest.fastf1_ingest.fastf1.get_event_schedule')
    @patch('ingest.fastf1_ingest.fastf1.get_session')
    def test_fetch_fastf1(self, mock_get_session, mock_get_event_schedule, mock_enable_cache):
        import pandas as pd
        # Mock event schedule
        now = pd.Timestamp.now()
        mock_events = pd.DataFrame({
            'EventDate': [now - pd.Timedelta(days=1)],
            'EventName': ['Test GP']
        })
        mock_get_event_schedule.return_value = mock_events
        # Mock session
        mock_session = MagicMock()
        mock_session.laps.to_json.return_value = '[{"Driver": "HAM", "LapNumber": 1, "Position": 1, "LapTime": 90000}]'
        mock_session.weather_data.to_json.return_value = '[{"temp": 20}]'
        mock_session.results.to_json.return_value = '[{"Driver": "HAM", "Position": 1}]'
        mock_get_session.return_value = mock_session
        mock_session.load.return_value = None
        result = ingest.fetch_fastf1()
        self.assertIn(b'laps', result)
        self.assertIn(b'weather', result)
        self.assertIn(b'results', result)

    def test_parse_args_defaults(self):
        with patch('sys.argv', ['script']):
            args = ingest.parse_args()
            self.assertTrue(hasattr(args, 'bucket'))
            self.assertTrue(hasattr(args, 'region'))
            self.assertTrue(hasattr(args, 'jolpica_url'))
            self.assertTrue(hasattr(args, 'include_fastf1'))
            self.assertTrue(hasattr(args, 'mock_file'))
            self.assertTrue(hasattr(args, 'retries'))

if __name__ == '__main__':
    unittest.main()
