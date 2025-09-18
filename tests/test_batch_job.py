import os
import unittest
from unittest.mock import patch, MagicMock

os.environ["F1_S3_BUCKET"] = "test-bucket"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_NAME"] = "test_db"
os.environ["DB_USER"] = "test_user"
os.environ["DB_PASS"] = "test_pass"

import batch.batch as batch

class TestBatchJob(unittest.TestCase):
    @patch('batch.batch.boto3.client')
    def test_list_new_objects(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {
            'Contents': [
                {'Key': 'raw/2025-09-13/jolpica/1757726296.json'},
                {'Key': 'raw/2025-09-16/fastf1/1757983471.json'}
            ]
        }
        result = list(batch.list_new_objects('jolpica'))
        self.assertIn('raw/2025-09-13/jolpica/1757726296.json', result)

    @patch('batch.batch.get_db_conn')
    @patch('batch.batch.fetch_object')
    def test_process_ergast_no_results(self, mock_fetch, mock_db):
        # Simulate Ergast JSON with no Results
        mock_fetch.return_value = '{"MRData": {"RaceTable": {"Races": [{"season": "2025", "round": "1", "raceName": "Test GP", "Circuit": {"circuitName": "Test Circuit", "Location": {"locality": "Test City", "country": "Testland"}}, "date": "2025-03-01"}]}}}'
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        race_id, driver_map = batch.process_ergast('fakekey')
        self.assertIsNone(race_id)
        self.assertEqual(driver_map, {})

    @patch('batch.batch.get_db_conn')
    @patch('batch.batch.fetch_object')
    def test_process_ergast_with_results(self, mock_fetch, mock_db):
        # Simulate Ergast JSON with Results
        mock_json = '{"MRData": {"RaceTable": {"Races": [{"season": "2025", "round": "1", "raceName": "Test GP", "Circuit": {"circuitName": "Test Circuit", "Location": {"locality": "Test City", "country": "Testland"}}, "date": "2025-03-01", "Results": [{"Driver": {"driverId": "hamilton", "givenName": "Lewis", "familyName": "Hamilton", "code": "HAM", "nationality": "British", "dateOfBirth": "1985-01-07"}, "Constructor": {"constructorId": "mercedes", "name": "Mercedes", "nationality": "German"}}]}]}}}'
        mock_fetch.return_value = mock_json
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(1,), (1, 'HAM'), (1, 'HAM')]
        mock_cursor.rowcount = 1
        race_id, driver_map = batch.process_ergast('fakekey')
        self.assertEqual(race_id, 1)
        self.assertIn('HAM', driver_map)

    @patch('batch.batch.get_db_conn')
    @patch('batch.batch.fetch_object')
    def test_process_fastf1_empty_laps(self, mock_fetch, mock_db):
        # Simulate FastF1 JSON with no laps
        mock_fetch.return_value = '{"laps": []}'
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        batch.process_fastf1('fakekey', 1, {'HAM': 1})
        mock_cursor.execute.assert_not_called()

if __name__ == '__main__':
    unittest.main()
