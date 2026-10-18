"""Software-only fixtures. No physical perfume measurements are shipped."""
import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
import uuid
import zipfile
import numpy as np
from olfy.backup import create_backup,restore_backup
from olfy.catalogue import FEATURE_SCHEME
from olfy.client import OlfyClient,OlfyError
from olfy.contracts import SensorInfo,UNITS
from olfy.demo import seed_demo
from olfy.features import FEATURE_VERSION,FEATURE_NAMES,extract,scan_profile
from olfy.model import predict,train
from olfy.recorder import Recorder
from olfy.server import make_server
from olfy.storage import Store
from test_integration import StubSensor,stub_registry


def fixture(store,fragrance,day='fixture-day-1',amplitude=.25,heater=320):
    info=SensorInfo('stub','fixture-device','fixture-profile',units=UNITS)
    sid=store.create('real',{'fragrance_id':fragrance['fragrance_id'],'label':fragrance['label'],
      'kind':'known','group_id':day,'bottle_id':'software-fixture','sample_id':uuid.uuid4().hex,
      'device_id':info.device_id,'profile':info.profile,'sampling_interval_s':1.,
      'acquisition_protocol':'reference-phases-v1','sensor':info.to_dict(),
      'substrate':'paper blotter','dose':'1 test dose','drydown_min':5})
    rows=[]
    for phase in ('baseline','exposure','recovery'):
        for t in range(12):
            response=0 if phase=='baseline' else -amplitude*(1-np.exp(-t/3)) if phase=='exposure' else -amplitude*np.exp(-t/2)
            rows.append({'sequence':len(rows),'elapsed_s':len(rows),'phase':phase,'phase_elapsed_s':t,
              'gas_ohm':float(100000*np.exp(response)),'temperature_c':23,'humidity_pct':40,
              'pressure_hpa':1013,'heater_c':heater,'heater_ms':150})
    store.append_many('real',sid,rows);store.finish('real',sid);return sid


def dataset(store,heater=320):
    perfumes=store.catalogue.snapshot()['fragrances'][:2];ids=[]
    for day in (1,2,3):
        for i,f in enumerate(perfumes):
            for rep in range(1 if day==3 else 2):ids.append(fixture(store,f,f'fixture-day-{day}',.2+i*.65,heater))
    return perfumes,ids


class MeasurementLinkTests(unittest.TestCase):
    def test_database_samples_features_model_and_perfume_identity_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);perfumes,ids=dataset(store);model=train(store,'real','fixture-day-3')
            sid=ids[-1];scan=store.get('real',sid);prediction=predict(model,scan)
            self.assertEqual(prediction['decision'],'match')
            self.assertEqual(prediction['fragrance_id'],perfumes[1]['fragrance_id'])
            self.assertEqual(FEATURE_SCHEME,model['feature_version'])
            data=store.catalogue.snapshot(perfumes[1]['fragrance_id'])
            m=next(m for m in data['measurements'] if m['scan_id']==sid)
            self.assertEqual([m['features'][n] for n in FEATURE_NAMES],extract(scan)[0].tolist())
            self.assertEqual(m['profile_key'],model['signal_profile_key'])
            self.assertEqual(m['sample_count'],36)
            self.assertEqual(store.catalogue.samples(sid)['readings'],scan['readings'])
            with store.catalogue.connect() as db:
                rows=db.execute('SELECT feature_name,value FROM perfume_sensor_features WHERE scan_id=?',(sid,)).fetchall()
                self.assertEqual(dict((r['feature_name'],r['value']) for r in rows),m['features'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM perfume_sensor_samples WHERE fragrance_id=?',(perfumes[1]['fragrance_id'],)).fetchone()[0],180)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            target=Path(tmp)/'export.sqlite3';target.write_bytes(store.catalogue.export_bytes())
            with sqlite3.connect(target) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reference_samples WHERE scan_id=?',(sid,)).fetchone()[0],36)

    def test_changed_heater_units_rate_and_sampling_conditions_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);_,ids=dataset(store);model=train(store,'real','fixture-day-3');original=store.get('real',ids[-1])
            for change in ('heater','units','rate'):
                scan=copy.deepcopy(original)
                if change=='heater':
                    for row in scan['readings']:row['heater_c']=400
                elif change=='units':scan['sensor']['units']['humidity_pct']='fraction'
                else:scan['sampling_interval_s']=.5
                with self.subTest(change=change),self.assertRaisesRegex(ValueError,'settings'):predict(model,scan)
            for field in ('substrate','dose','drydown_min'):
                scan=copy.deepcopy(original);scan[field]=10 if field=='drydown_min' else 'different conditions'
                self.assertEqual(predict(model,scan)['decision'],'unknown')
            legacy=copy.deepcopy(model);legacy.pop('signal_profile_key')
            with self.assertRaisesRegex(ValueError,'older real model'):predict(legacy,original)

    def test_cohorts_keep_different_heaters_separate_even_if_profile_name_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);_,ids=dataset(store,320);dataset(store,400)
            key=scan_profile(store.get('real',ids[0]))[0]
            with self.assertRaisesRegex(ValueError,'Mixed sensor settings'):train(store,'real','fixture-day-3')
            model=train(store,'real','fixture-day-3',key)
            self.assertEqual(model['signal_profile_key'],key);self.assertEqual(model['report']['train_count'],8)
            cohorts=store.catalogue.readiness(store)['cohorts'];self.assertEqual(len(cohorts),2)
            self.assertTrue(all('fixture-day-3' in c['candidate_test_days'] for c in cohorts))
            self.assertEqual(sum(c['scan_count'] for c in cohorts),20)

    def test_legacy_catalogue_migration_preserves_raw_data_and_rebuilds_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);f=store.catalogue.snapshot()['fragrances'][0];sid=fixture(store,f)
            with store.catalogue.connect() as db:
                db.execute('DELETE FROM reference_features');db.execute('DELETE FROM reference_samples')
                db.execute("UPDATE reference_measurements SET feature_scheme='log-gas-reference-v1'")
                db.execute("UPDATE catalogue_metadata SET value='1' WHERE key='schema_version'")
            reopened=Store(tmp);data=reopened.catalogue.snapshot(f['fragrance_id'])
            self.assertEqual(data['schema_version'],2);self.assertEqual(data['measurements'][0]['feature_scheme'],FEATURE_VERSION)
            self.assertEqual(data['measurements'][0]['sample_count'],36)
            self.assertEqual(len(reopened.get('real',sid)['readings']),36)
            self.assertEqual(reopened.catalogue.summary()['reference_count'],1)

    def test_index_failure_preserves_the_scan_and_recovers_on_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);f=store.catalogue.snapshot()['fragrances'][0]
            with patch.object(store.catalogue,'index_reference',side_effect=ValueError('index fixture failure')):sid=fixture(store,f)
            self.assertEqual(store.get('real',sid)['status'],'complete');self.assertEqual(len(store.index_errors),1)
            recovered=Store(tmp);self.assertEqual(recovered.index_errors,[])
            self.assertEqual(recovered.catalogue.summary()['usable_count'],1)


class ReliabilityTests(unittest.TestCase):
    def test_training_history_is_preserved_with_source_data_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);seed_demo(store)
            first=train(store,'simulation','demo-day-4');second=train(store,'simulation','demo-day-3')
            self.assertNotEqual(first['model_id'],second['model_id'])
            self.assertEqual(len(store.model_runs('simulation')),2)
            self.assertEqual(store.model_run('simulation',first['model_id']),first)
            self.assertEqual(len(first['data_digest']),64)
            reopened=Store(tmp)
            self.assertEqual(len(reopened.model_runs('simulation')),2)
            self.assertEqual(reopened.load_model('simulation')['model_id'],second['model_id'])

    def test_backup_roundtrip_preserves_curves_fingerprints_models_and_saved_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=Store(Path(tmp)/'original');seed_demo(original);train(original,'simulation','demo-day-4')
            sid=original.list('simulation')[0]['id'];original.bookmark('simulation',sid)
            f=original.catalogue.snapshot()['fragrances'][0];rid=fixture(original,f);original.bookmark('real',rid)
            path=Path(tmp)/'backup.zip';path.write_bytes(create_backup(original));target=Path(tmp)/'restored'
            manifest=restore_backup(path,target);restored=Store(target)
            self.assertEqual(manifest['counts'],{'real':1,'simulation':68})
            self.assertEqual(restored.get('real',rid),original.get('real',rid))
            self.assertEqual(restored.bookmarks('real'),[rid]);self.assertEqual(restored.bookmarks('simulation'),[sid])
            self.assertEqual(restored.load_model('simulation'),original.load_model('simulation'))
            self.assertEqual(restored.catalogue.samples(rid)['readings'],original.get('real',rid)['readings'])
            with self.assertRaisesRegex(ValueError,'empty data folder'):restore_backup(path,target)
            self.assertEqual(len(restored.list('real')),1)

    def test_corrupt_and_traversal_backups_are_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            good=create_backup(Store(Path(tmp)/'source'))
            for case in ('checksum','path'):
                output=io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(good)) as source,zipfile.ZipFile(output,'w') as changed:
                    for name in source.namelist():
                        data=source.read(name)
                        if case=='checksum' and name=='real.sqlite3':data+=b'tampered'
                        changed.writestr(name,data)
                    if case=='path':changed.writestr('../outside.txt','forbidden')
                path=Path(tmp)/f'{case}.zip';path.write_bytes(output.getvalue());target=Path(tmp)/f'restored-{case}'
                with self.subTest(case=case),self.assertRaises(ValueError):restore_backup(path,target)
                self.assertFalse(target.exists());self.assertFalse((Path(tmp)/'outside.txt').exists())

    def test_a_second_app_cannot_reset_an_active_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,server=make_server(tmp,0)
            try:
                sid=app.recorder.start('simulation',{'label':'Demo A','group_id':'fixture'})
                with self.assertRaisesRegex(ValueError,'already open'):make_server(tmp,0)
                self.assertEqual(app.store.get('simulation',sid)['status'],'recording');app.recorder.finish(abort=True)
            finally:server.server_close()
            reopened,second=make_server(tmp,0);second.server_close()

    def test_api_bookmarks_are_durable_and_active_scans_block_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            app,server=make_server(tmp,0,registry=stub_registry(StubSensor()))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}';client=OlfyClient(base)
            try:
                client.load_demo();sid=client.state()['scans'][0]['id']
                client.save_scan(sid,mode='simulation');client.save_scan(sid,mode='simulation')
                self.assertEqual(client.state()['saved_scan_ids'],[sid])
                with self.assertRaises(OlfyError):client.save_scan(sid,'yes',mode='simulation')
                client.save_scan(sid,False,mode='simulation');self.assertEqual(client.state()['saved_scan_ids'],[])
                client.connect_sensor('stub')
                active=client.start_capture({'label':'Fixture','group_id':'fixture','bottle_id':'fixture','warmup_ack':True},5)['scan_id']
                with self.assertRaises(HTTPError) as e:urlopen(base+'/api/v1/backup')
                self.assertEqual(e.exception.code,400);client.finish_scan(active,abort=True)
                with urlopen(base+'/api/v1/backup') as response:data=response.read()
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    self.assertEqual(json.loads(archive.read('backup_manifest.json'))['counts'],{'real':1,'simulation':68})
                self.assertEqual(client.readiness()['mode'],'real');self.assertEqual(len(client.readiness('simulation')['cohorts']),1)
            finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_storage_fault_does_not_leave_the_recorder_or_sensor_stuck(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);source=StubSensor();recorder=Recorder(store,interval=.01,registry=stub_registry(source))
            try:
                recorder.connect('stub')
                with patch.object(store,'append',side_effect=OSError('storage fixture failure')),patch.object(store,'finish',side_effect=OSError('status fixture failure')):
                    recorder.start('real',{'label':'Fixture','group_id':'fixture','bottle_id':'fixture','warmup_ack':True})
                    deadline=time.monotonic()+2
                    while recorder.status()['active'] is not None and time.monotonic()<deadline:time.sleep(.02)
                    self.assertIsNone(recorder.status()['active']);self.assertIsNone(recorder.status()['connected_mode'])
                    self.assertTrue(recorder.thread.is_alive());self.assertTrue(source.closed)
                    self.assertIn('storage fixture failure',recorder.status()['error'])
            finally:recorder.close()


if __name__=='__main__':unittest.main()
