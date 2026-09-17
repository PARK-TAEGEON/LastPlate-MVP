"""Explicit demo meal data, separate from the supplied Agent implementations."""
from calendar import monthrange
from datetime import date, timedelta

SLOTS={'rice':'밥','soup':'국','main':'메인반찬','side':'사이드반찬'}
CATALOG={'rice':['백미밥','잡곡밥'],'soup':['된장국','미역국','콩나물국'],
         'main':['제육볶음','닭갈비','소고기볶음'],'side':['두부조림','계란찜','계란말이','버섯볶음']}

def month_days(month):
    first=date.fromisoformat(month+'-01')
    return [str(first+timedelta(days=i)) for i in range(monthrange(first.year,first.month)[1])]

def demo_days(month):
    return [{'date':day,'menus':{slot:names[index%len(names)] for slot,names in CATALOG.items()},
             'change':{'reason':'','increase':0,'decrease':0,'note':''}} for index,day in enumerate(month_days(month))]

def complete_meals(payload,target):
    extra=[('백미밥','rice',[('쌀',90)]),('잡곡밥','rice',[('쌀',70),('잡곡',20)]),
           ('된장국','soup',[('된장',12),('두부',20),('양파',15)]),
           ('미역국','soup',[('미역',4),('소고기',15),('간장',2)]),
           ('콩나물국','soup',[('콩나물',45),('소금',1)])]
    payload['recipes'] += [dict(recipe_id='DEMO-MEAL-'+str(i),menu_name=name,category=category,
        ingredients=[dict(ingredient=n,amount_per_serving=amount,unit='g') for n,amount in ingredients])
        for i,(name,category,ingredients) in enumerate(extra)]
    nutrients=[('쌀',360,6.5,79,.5,2),('잡곡',350,9,72,2,3),('된장',190,12,20,6,3700),
               ('미역',160,15,40,2,900),('콩나물',30,3,4,.5,5)]
    payload['nutrition'] += [dict(ingredient=n,serving_basis=100,kcal=k,protein=p,carbohydrate=c,fat=f,sodium=s,allergens=['대두'] if n in ('된장','콩나물') else []) for n,k,p,c,f,s in nutrients]
    extra_stock=[('쌀',246.8,2780,90),('잡곡',52.4,4650,75),('된장',31.65,5200,45),('미역',9.35,14800,120),('콩나물',61.7,1850,5)]
    for n,amount,price,days in extra_stock:
        payload['inventory'].append(dict(ingredient=n,current_stock=amount,unit='kg',expiry_date=str(target+timedelta(days=days)),unit_price=price,minimum_stock=2.5,planned_order=0,storage_type='refrigerated' if n in ('된장','콩나물') else 'ambient',last_used_date=str(target-timedelta(days=1))))
        payload['prices'].append(dict(date=str(target),ingredient=n,current_price=price,price_1w_ago=price,price_2w_ago=price,price_3w_ago=price,price_4w_ago=price,unit='kg'))
        payload['monthly_prices'].append(dict(year_month=str(target)[:7],ingredient=n,average_price=price,unit='kg'))
    day=demo_days(str(target)[:7])[target.day-1]
    payload['weekly_menu']=[dict(date=str(target),meal_type='lunch',menu_name=name) for name in day['menus'].values()]
    return payload
