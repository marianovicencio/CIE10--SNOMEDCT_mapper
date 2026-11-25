import json,tempfile,unittest
from pathlib import Path
from cie10.retrieval.retrieval_configuration import load_active_index, EDITION
from cie10.api.mapping_context import ContextError
from cie10.retrieval.retrieval_core import sha256

class ConfigurationTests(unittest.TestCase):
 def test_full_default_explicit_switch_and_fail_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);base=root/'data/indexes/snomed';pilot=base/'pilot-20261110-v1';full=base/'full-es-20261110-v1'
   meta={'status':'completed','schema_version':'0.2.0','catalog':{'version':EDITION}}
   for folder in (pilot,full):folder.mkdir(parents=True);(folder/'index.json').write_text(json.dumps(meta))
   self.assertEqual(load_active_index(root)[0],full)
   config=root/'infra/retrieval/active-index.json';config.parent.mkdir(parents=True)
   pointer={'path':str(full.relative_to(root)),'index_manifest_sha256':sha256(full/'index.json')};config.write_text(json.dumps(pointer))
   self.assertEqual(load_active_index(root)[0],full)
   (full/'index.json').write_text(json.dumps({**meta,'status':'building'}))
   with self.assertRaises(ContextError):load_active_index(root)
   config.write_text(json.dumps({'path':'../outside'}))
   with self.assertRaises(ContextError):load_active_index(root)
