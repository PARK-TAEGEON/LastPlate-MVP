"""Request-local, gram-exact usable stock and FEFO allocation (no reservations)."""
from datetime import date
from app.engine.decision_engine import _kg_to_g


def stock_snapshot(payload):
    stock, rows, advisories = {}, [], []
    meal_date = date.fromisoformat(payload['meal_date'])
    for item in payload['inventory']:
        ingredient = item['ingredient']
        lots = item.get('lots') or [{
            'id': 'aggregate', 'quantity_kg': item.get('physical_kg', item.get('available_kg', 0)),
            'reserved_kg': item.get('reserved_kg', 0), 'expires_on': item.get('expires_on'),
        }]
        lots = sorted(lots, key=lambda lot: (lot.get('expires_on') or '9999-12-31', lot['id']))
        detail = []
        for lot in lots:
            physical = _kg_to_g(lot['quantity_kg'], ingredient)
            reserved = _kg_to_g(lot.get('reserved_kg', 0), ingredient)
            expiry = date.fromisoformat(lot['expires_on']) if lot.get('expires_on') else None
            days = (expiry - meal_date).days if expiry else None
            expired = physical - reserved if days is not None and days < 0 else 0
            usable = physical - reserved - expired
            detail.append(dict(lot_id=lot['id'], expires_on=lot.get('expires_on'),
                               physical_kg=physical/1000, reserved_kg=reserved/1000,
                               expired_kg=expired/1000, usable_kg=usable/1000,
                               allocated_kg=0, remaining_kg=usable/1000))
            if days is not None and days <= 1 and physical > reserved:
                advisories.append(dict(
                    code='EXPIRED_STOCK' if days < 0 else 'USE_FIRST_EXPIRING_STOCK',
                    severity='critical' if days < 0 else 'warning', ingredient=ingredient,
                    expires_on=expiry, days_until_expiry=days,
                    message=(f'{ingredient} / {lot["id"]}: 기한 경과 재고를 가용량에서 제외했습니다.' if days < 0
                             else f'{ingredient} / {lot["id"]}: 식사일 기준 D-{days}, 우선 소진 검토.')))
        row = dict(ingredient=ingredient, source='lots' if item.get('lots') else
                   ('physical_less_reserved' if 'physical_kg' in item else 'net_available'), lots=detail)
        for key in ('physical_kg', 'reserved_kg', 'expired_kg', 'usable_kg'):
            row[key] = sum(_kg_to_g(lot[key], ingredient) for lot in detail)/1000
        rows.append(row)
        stock[ingredient] = row['usable_kg']
    return stock, rows, advisories


def allocate_lots(rows, decision):
    allocation = {row['ingredient']: row['allocated_kg'] for row in decision['inventory']}
    for row in rows:
        remaining = _kg_to_g(allocation.get(row['ingredient'], 0), row['ingredient'])
        row['allocated_kg'] = remaining/1000
        row['remaining_kg'] = (_kg_to_g(row['usable_kg'], row['ingredient'])-remaining)/1000
        for lot in row['lots']:
            usable = _kg_to_g(lot['usable_kg'], row['ingredient'])
            assigned = min(remaining, usable)
            lot['allocated_kg'], lot['remaining_kg'] = assigned/1000, (usable-assigned)/1000
            remaining -= assigned
    return rows
