import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('retriever_downloads',
    Path(__file__).resolve().parents[1]/'scripts/download_retriever_models.py')
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)


class Response(BytesIO):
    status = 200
    headers = {}


class RetrieverDownloadTests(unittest.TestCase):
    def test_ignored_range_is_rejected_without_writing_or_concatenating(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'part'
            with patch.object(download, 'urlopen', side_effect=lambda *a, **k: Response(b'wrong bytes')):
                with patch.object(download.time, 'sleep'):
                    with self.assertRaisesRegex(ValueError, 'intervalo'):
                        download.fetch('https://example.org/weights', target, 10, 19)
            self.assertFalse(target.exists())

    def test_existing_weights_with_wrong_hash_are_not_overwritten(self):
        revision = 'a'*40
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            snapshot = cache/'models--test--encoder'/'snapshots'/revision
            snapshot.mkdir(parents=True)
            target = snapshot/'model.safetensors'
            target.write_bytes(b'bad')
            meta = {'sha': revision, 'gated': False, 'siblings': [
                {'rfilename': 'model.safetensors', 'size': 3,
                 'lfs': {'sha256': hashlib.sha256(b'yes').hexdigest()}}]}
            with patch.object(download, 'urlopen', return_value=Response(json.dumps(meta).encode())):
                with self.assertRaisesRegex(ValueError, 'previo distinto'):
                    download.download_model('test', {'repository': 'test/encoder', 'revision': revision}, cache, 1)
            self.assertEqual(target.read_bytes(), b'bad')

    def test_unpinned_revisions_fail_before_network_access(self):
        with patch.object(download, 'urlopen') as request:
            with self.assertRaisesRegex(ValueError, 'revisión exacta'):
                download.download_model('test', {'repository': 'test/encoder', 'revision': 'main'}, Path('.'), 1)
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
