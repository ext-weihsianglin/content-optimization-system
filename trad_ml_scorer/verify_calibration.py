"""Verify v8 OOF provenance, exact base binding and public document-score parity."""
import gzip
import json
import numpy as np
from trad_ml_scorer.calibration_experiment import BASE,OUTPUT,ROOT
from trad_ml_scorer.predict_platt import load_calibrated_model,predict_calibrated_document
from trad_ml_scorer.prepare_semantic import digest
from trad_ml_scorer.retrain_markdownify import CORPUS
from trad_ml_scorer.semantic_features import NAMES


def main():
    result=json.loads((ROOT/'results.json').read_text());provenance=result['provenance']
    assert digest(OUTPUT/'training_oof.npz')==provenance['training_oof_sha256']
    assert digest(OUTPUT/'calibration.joblib')==result['calibration_sha256']
    d=np.load(BASE/'features.npz');oof=np.load(OUTPUT/'training_oof.npz')
    tr=d['splits']=='train'
    for key,original in [('record_ids','ids'),('labels','y'),('hosts','hosts')]:
        np.testing.assert_array_equal(oof[key],d[original][tr])
    assert len(set(oof['record_ids']))==len(oof['logits'])==7540
    assert np.isfinite(oof['logits']).all()
    for audit in provenance['folds']:
        mask=oof['fold']==audit['fold']
        assert set(oof['hosts'][mask])==set(audit['score_hosts'])
        assert set(oof['hosts'][~mask])==set(audit['fit_hosts'])
        assert not set(audit['score_hosts'])&set(audit['fit_hosts'])
        assert int(mask.sum())==audit['score_rows']
    model=load_calibrated_model(OUTPUT/'calibration.joblib')
    lookup={str(identity):i for i,identity in enumerate(d['ids'])}
    with open(BASE/'joined_records.jsonl') as stream:
        sources={r['record_id']:r for r in map(json.loads,stream)}
    with open(BASE.parent/'v2/records.jsonl') as stream:
        records={r['record_id']:r for r in map(json.loads,stream)}
    predictions=json.loads((ROOT/'validation_predictions.json').read_text())
    sample=sorted(predictions,key=lambda r:r['record_id'])[:20]
    errors=[]
    for row in sample:
        rid=row['record_id'];i=lookup[rid];source=sources[rid]
        assert d['splits'][i]=='validation'
        with gzip.open(CORPUS/'documents'/(source['snapshot_id']+'.json.gz'),'rt') as stream:doc=json.load(stream)
        got=predict_calibrated_document(model,records[rid]['prompt'],doc,dict(zip(NAMES,d['X'][i,:10])))
        np.testing.assert_allclose([got['raw_logit'],got['uncalibrated_high_class_probability'],got['calibrated_high_class_probability']],
                                   [row['raw_logit'],row['v7_1_probability'],row['v8_probability']],atol=1e-12,rtol=0)
        errors.append(abs(got['calibrated_high_class_probability']-row['v8_probability']))
    report={'oof_rows':len(oof['logits']),'fold_host_isolation_verified':True,'base_model_checksum_verified':True,
            'document_adapter_parity_rows':len(sample),'max_calibrated_probability_error':max(errors),
            'sample_record_ids':[r['record_id'] for r in sample], 'semantic_scores_reused':True,
            'test_evaluated':False,'verification_code_sha256':digest(__file__)}
    (ROOT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
