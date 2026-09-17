"""Diagnose native calculation on this PC without changing the operational DB."""
import sys
import tempfile
import traceback
from datetime import date
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    print('Python:',sys.version.split()[0],flush=True)
    for package in ('fastapi','pydantic','numpy','pandas','scikit-learn','lightgbm','xgboost','joblib','filelock','langgraph','openpyxl'):
        try:print(package,version(package),flush=True)
        except PackageNotFoundError:print(package,'NOT INSTALLED',flush=True)
    try:
        from backend.application.profiles import demo_profile
        from backend.application.service import plan
        from backend.contracts import PlanRequest
        from backend.settings import Settings
        with tempfile.TemporaryDirectory(prefix='lastplate-check-') as scratch:
            request=PlanRequest.model_validate(demo_profile(target_date=date(2026,9,19))['request'])
            result=plan(request,Settings(Path(scratch)/'check.db'))
            print('Calculation:',result['pipeline_status'],flush=True)
            for error in result['errors']:
                print(error.get('stage'),error.get('code'),error.get('original_message') or error.get('message'),flush=True)
            if result['pipeline_status']!='SUCCESS':return 1
            print('All four calculation stages completed. Operational DB was not used.',flush=True)
            return 0
    except Exception:
        traceback.print_exc()
        return 1

if __name__=='__main__':sys.exit(main())
