import csv, hashlib
from ..contracts import DemandResult

def adapt_demand(raw, metadata, training_csv):
    # Use the selected saved model's actual deployment fit period, not a UI default.
    with training_csv.open(encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if metadata['train_period']['start']<=r['date']<=metadata['train_period']['end']]
    csv_hash=hashlib.sha256(training_csv.read_bytes()).hexdigest()
    if csv_hash!=metadata.get('data_sha256') or len(rows)!=metadata['train_period']['rows']:
        return DemandResult(prediction_id=raw['prediction_id'],target_date=raw['target_date'],predicted_diners=raw['prediction'],
            model_version=raw['model_version'],model_type=metadata.get('model_type'),applicability='UNKNOWN',confidence='LOW',
            warnings=[dict(code='TRAINING_EVIDENCE_MISMATCH',category='EVIDENCE_UNKNOWN',severity='HIGH',
                message='Saved model training data hash or row count does not match; range claims withheld')],source_payload=raw).model_dump(mode='json')
    features=['employees','vacation','business_trip','work_from_home','overtime']
    ranges={k:{'min':min(float(r[k]) for r in rows),'max':max(float(r[k]) for r in rows)} for k in features}
    warnings=[]
    for key,limits in ranges.items():
        v=raw['input_data'].get(key)
        if v is not None and not limits['min']<=v<=limits['max']:
            warnings.append(dict(code='MODEL_INPUT_OUT_OF_RANGE',category='OOD',severity='HIGH',feature=key,value=v,
                training_range=limits,message=f'{key}={v} is outside training range [{limits["min"]}, {limits["max"]}]'))
    return DemandResult(prediction_id=raw['prediction_id'],target_date=raw['target_date'],predicted_diners=raw['prediction'],
        model_version=raw['model_version'],model_type=metadata.get('model_type'),
        applicability='OUT_OF_DISTRIBUTION' if warnings else 'IN_RANGE',confidence='LOW' if warnings else 'UNKNOWN',
        warnings=warnings,training_ranges={'features':ranges,'period':metadata['train_period'],
            'csv_sha256':hashlib.sha256(training_csv.read_bytes()).hexdigest(),
            'model_data_sha256':metadata.get('data_sha256'),
            'limitation':'Marginal range check only; IN_RANGE does not establish site generalization or calibrated confidence.'},
        source_payload=raw).model_dump(mode='json')
