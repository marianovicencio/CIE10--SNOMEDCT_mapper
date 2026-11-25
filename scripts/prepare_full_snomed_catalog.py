from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cie10.full_snomed_catalog import import_archives
from cie10.explanation_service import VERSION
from cie10.snowstorm_verification import SnowstormFHIR

if __name__=='__main__':
    SnowstormFHIR('http://127.0.0.1:8081/fhir',VERSION).require_version()
    result=import_archives(ROOT/'snomed/SnomedCT_InternationalRF2_PRODUCTION_20261001T120000Z.zip',
        ROOT/'snomed/SnomedCT_SpanishRelease-es_PRODUCTION_20261110T120000Z.zip',VERSION,'20261001',
        ROOT/'data/catalogs/snomed/full-es-20261110-v1')
    print(json.dumps(result['counts']),flush=True)
