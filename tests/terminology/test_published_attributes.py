"""Published FHIR attributes must preserve their exact source."""
import unittest
from types import SimpleNamespace
from cie10.api.mapping_context import ContextError, digest
from cie10.terminology.snowstorm_verification import published_attributes

class AttributeTests(unittest.TestCase):
    def test_attributes_require_unchanged_source(self):
        resolver = SimpleNamespace(
            verifier=SimpleNamespace(get=lambda _: {"parameter": []})
        )
        with self.assertRaises(ContextError):
            published_attributes(
                {"request_path": "/lookup", "response_sha256": "changed"}, resolver
            )

    def test_attribute_projection_preserves_parts_and_excludes_children(self):
        site = {
            "name": "property",
            "part": [
                {"name": "code", "valueCode": "363698007"},
                {"name": "description", "valueString": "sitio publicado"},
                {"name": "value", "valueCode": "123"},
            ],
        }
        child = {
            "name": "property",
            "part": [
                {"name": "code", "valueCode": "child"},
                {"name": "value", "valueCode": "456"},
            ],
        }
        data = {"parameter": [site, child]}
        resolver = SimpleNamespace(verifier=SimpleNamespace(get=lambda _: data))
        verified = {"request_path": "/lookup", "response_sha256": digest(data)}
        self.assertEqual(published_attributes(verified, resolver), [site])
