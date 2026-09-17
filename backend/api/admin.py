"""Authenticated configuration, separate from diagnostic raw request editing."""
import json
from datetime import date,timedelta
from fastapi import APIRouter,Depends,Request
from backend.api.access import developer_access
from backend.api.routes import database
from backend.api.workspace import baseline
from backend.contracts import SiteSettings,PlanRequest
from backend.adapters.persistence import now

router=APIRouter(prefix='/api/admin',dependencies=[Depends(developer_access)])

def view(db,site_id,target):
    data=baseline(db,site_id,target)
    constraints=data['operation_policy'].get('constraints',{})
    calories=constraints.get('calorie_range',[0,0])
    settings={'registered_population':data['attendance']['registered_population'],'meal_capacity':data['meal_capacity'],
        'safety_margin_pct':data['operation_policy'].get('safety_margin_pct',0),
        'minimum_protein':constraints.get('minimum_protein',0),'calorie_min':calories[0],
        'calorie_max':calories[1],'sodium_max':constraints.get('sodium_max',0),
        'allergy_restriction':constraints.get('allergy_restriction',[])}
    row=db.repo.connection.execute('SELECT updated_at FROM api_site_settings WHERE site_id=?',(site_id,)).fetchone()
    return {'site_name':data['site_name'],'settings':settings,'updated_at':row[0] if row else None,
        'recipes':[{'menu':r['menu_name'],'ingredients':[{'ingredient':i['ingredient'],'amount':i['amount_per_serving'],'unit':i['unit']} for i in r['ingredients']]} for r in data['recipes']],
        'prices':[{'ingredient':r['ingredient'],'price':r['current_price'],'unit':r['unit'],'date':r['date']} for r in data['prices']]}

@router.get('/settings/{site_id}')
def get_settings(site_id:str,request:Request,target_date:date|None=None):
    with database(request) as db:return view(db,site_id,target_date or date.today()+timedelta(days=1))

@router.put('/settings/{site_id}')
def save_settings(site_id:str,payload:SiteSettings,request:Request,target_date:date|None=None):
    target=target_date or date.today()+timedelta(days=1)
    with database(request) as db:
        # Validate the resulting context, not only individual settings.
        data=baseline(db,site_id,target)
        data['attendance']['registered_population']=payload.registered_population
        PlanRequest.model_validate(data)
        with db.repo.transaction():
            db.repo.connection.execute('INSERT INTO api_site_settings VALUES (?,?,?) ON CONFLICT(site_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at',
                (site_id,json.dumps(payload.model_dump(),ensure_ascii=False,allow_nan=False),now()))
        return view(db,site_id,target)
