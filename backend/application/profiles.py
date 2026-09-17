import json
from datetime import date, timedelta
from backend.bootstrap import NATIVE
from backend.contracts import PlanRequest
from backend.application.meal_catalog import complete_meals


def demo_profile(profile='lh-like',target_date=None):
    target=target_date or date.today()+timedelta(days=1)
    p=json.loads((NATIVE/'examples/lh_like.json').read_text(encoding='utf-8'))
    origin=date.fromisoformat(p['target_date'])
    delta=target-origin
    def shift(value):
        if isinstance(value,list):return [shift(v) for v in value]
        if isinstance(value,dict):return {k:shift(v) for k,v in value.items()}
        if isinstance(value,str) and len(value)==10 and value[4]=='-' and value[7]=='-':
            try:return str(date.fromisoformat(value)+delta)
            except ValueError:pass
        return value
    p=shift(p)
    p.pop('request_id')
    p.update(site_id='DEMO-LH' if profile!='small-site' else 'DEMO-SMALL',
             site_name='LH 유사 시연 사업장' if profile!='small-site' else '소규모 시연 사업장',is_demo=True,events=[])
    p['attendance'].update(registered_population=600 if profile=='small-site' else 3000,
                           vacation=30,business_trip=50,work_from_home=10,overtime=50)
    if profile!='risk-demo':
        p['supply_events']=[]
        stocks=[42.6,18.75,91.3,138.7,106.4,37.8,24.6,44.2,23.9,12.8,72.35]
        for index,row in enumerate(p['inventory']):
            row.update(current_stock=stocks[index%len(stocks)],unit='kg',expiry_date=str(target+timedelta(days=5+index)),
                       minimum_stock=round(1.5+index*.65,2),planned_order=0,last_used_date=str(target-timedelta(days=1)))
        for row in p['prices']:
            for key in ('current_price','price_1w_ago','price_2w_ago','price_3w_ago','price_4w_ago'):row[key]=1000
        for row in p['monthly_prices']:row['average_price']=1000
    p=complete_meals(p,target)
    p['planned_orders']=[{'ingredient':x,'planned_order':0,'unit':'kg'} for x in ('두부','간장')]
    return {'profile':profile,'request':PlanRequest.model_validate(p).model_dump(mode='json'),
            'warnings':['시연 입력입니다. 예측값은 저장된 실제 모델에서 계산하며 레시피·영양·가격·재고는 DEMO입니다.']+
            (['600명 사업장은 학습범위 밖입니다. OOD 경고를 확인하세요.'] if profile=='small-site' else [])}
