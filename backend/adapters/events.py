import json, os, subprocess, sys
from pathlib import Path


def interpret(request):
    if not request.events:
        return {'events': [], 'diagnostics': [], 'attendance_delta': 0}
    ingredients = sorted({i['ingredient'] for r in request.recipes for i in r['ingredients']})
    payload = dict(events=request.events, as_of=str(request.as_of), target_date=str(request.target_date), ingredients=ingredients)
    result = subprocess.run([sys.executable, str(Path(__file__).with_name('event_worker.py'))],
        input=json.dumps(payload, ensure_ascii=False), text=True, encoding='utf-8',
        capture_output=True, timeout=30, env={**os.environ, 'PYTHONUTF8': '1'})
    if result.returncode:
        raise ValueError('이벤트를 해석하지 못했습니다. 날짜와 인원 변동을 확인하세요.')
    return json.loads(result.stdout)
