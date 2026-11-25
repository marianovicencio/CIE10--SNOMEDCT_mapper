import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile
from cie10.full_snomed_catalog import import_archives,insert_component
from cie10.mapping_context import ContextError

VERSION='http://snomed.info/sct/449081005/version/20261110'
CORE='900000000000207008'
MODEL='900000000000012004'
SPANISH='450829007'


def archive(path,date,concepts,descriptions,target):
    with ZipFile(path,'w') as z:
        for kind,header,data in [
            ('Concept',['id','effectiveTime','active','moduleId','definitionStatusId'],concepts),
            ('Description',['id','effectiveTime','active','moduleId','conceptId','languageCode','typeId','term','caseSignificanceId'],descriptions)]:
            s=io.StringIO();writer=csv.writer(s,delimiter='\t',quoting=csv.QUOTE_NONE,quotechar=None,escapechar=None,lineterminator='\n');writer.writerow(header);writer.writerows(data)
            z.writestr('Package/Snapshot/Terminology/sct2_'+kind+'_Snapshot_'+date+'.txt',s.getvalue())
        s='id\teffectiveTime\tactive\tmoduleId\trefsetId\treferencedComponentId\tsourceEffectiveTime\ttargetEffectiveTime\n'
        s+='00000000-0000-0000-0000-000000000001\t'+date+'\t1\t'+(SPANISH if 'es' in path.name else CORE)+'\t900000000000534007\t'+(CORE if 'es' in path.name else MODEL)+'\t'+date+'\t'+target+'\n'
        z.writestr('Package/Snapshot/Refset/Metadata/der2_ModuleDependencySnapshot_'+date+'.txt',s)


class FullCatalogTests(unittest.TestCase):
    def test_composition_respects_inactivation_and_publishes_only_active_spanish_names(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);base=folder/'base.zip';es=folder/'es.zip'
            concepts=[['100001','20261001','1',CORE,'900000000000074008'],['100002','20261001','1',CORE,'900000000000074008']]
            desc=[['200001','20261001','1',CORE,'100001','es','900000000000013009','Nombre retirado','900000000000448009'],
                  ['200002','20261001','1',CORE,'100002','es','900000000000013009','Concepto retirado','900000000000448009'],
                  ['200003','20261001','1',CORE,'100001','en','900000000000013009','English name','900000000000448009']]
            archive(base,'20261001',concepts,desc,'20261001')
            update=[['100002','20261110','0',CORE,'900000000000074008']]
            names=[['200001','20261110','0',CORE,'100001','es','900000000000013009','Nombre retirado','900000000000448009'],
                   ['200004','20261110','1',SPANISH,'100001','es','900000000000013009','"Nombre publicado"','900000000000448009']]
            archive(es,'20261110',update,names,'20261001')
            result=import_archives(base,es,VERSION,'20261001',folder/'out')
            rows=[json.loads(x) for x in (folder/'out/catalog.jsonl').read_text().splitlines()]
            self.assertEqual(result['counts']['concepts'],1)
            self.assertEqual(result['counts']['aliases'],1)
            self.assertEqual(rows[0]['term'],'"Nombre publicado"')
            self.assertTrue(result['module_dependencies_validated'])

    def test_wrong_international_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);base=folder/'base.zip';es=folder/'es.zip'
            archive(base,'20261001',[],[],'20261001');archive(es,'20261110',[],[],'20260901')
            with self.assertRaises(ContextError):import_archives(base,es,VERSION,'20261001',folder/'out')

    def test_same_date_conflicts_are_not_silently_overwritten(self):
        db=sqlite3.connect(':memory:');db.execute('CREATE TABLE c(id TEXT PRIMARY KEY,effective_time TEXT,active INT)')
        insert_component(db,'c',('100001','20260101',1))
        insert_component(db,'c',('100001','20260101',1))
        with self.assertRaises(ContextError):insert_component(db,'c',('100001','20260101',0))
        insert_component(db,'c',('100001','20260201',0))
        self.assertEqual(db.execute('SELECT active FROM c').fetchone()[0],0)
        insert_component(db,'c',('100001','20250101',1))
        self.assertEqual(db.execute('SELECT active FROM c').fetchone()[0],0)


if __name__=='__main__':unittest.main()
