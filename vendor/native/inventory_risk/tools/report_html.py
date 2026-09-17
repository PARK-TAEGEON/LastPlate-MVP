"""Offline, escaped read-only report. No operational approval/write controls."""
import html
import json

def render_report(report):
    esc=lambda v: html.escape(str(v))
    cards=[]
    for a in report["alerts"]:
        cards.append(f'<li><b>{esc(a.get("severity",""))} · {esc(a["type"])}</b> {esc(a.get("ingredient",a.get("affected_ingredient","")))}<p>{esc(" / ".join(a.get("evidence",[])))}</p></li>')
    rows=[]
    for c in report["substitute_candidates"]:
        rows.append('<tr>'+''.join(f'<td>{esc(v)}</td>' for v in [c['date'],c['original_menu'],c['candidate_menu'],c['nutrition_check'],c['inventory_available'],c['price_effect'],c['eligible_for_review']])+'</tr>')
    payload=esc(json.dumps(report,ensure_ascii=False,indent=2))
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LastPlate Inventory & Risk — DEMO</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;color:#173344;background:#f3f6f7;margin:0}}main{{max-width:1100px;margin:32px auto;padding:24px}}header,section{{background:white;padding:24px;margin-bottom:20px;border-radius:12px}}h1{{margin:0}}.banner{{background:#fff2c9;padding:12px;border-radius:8px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}li{{padding:10px}}li p{{margin:0;color:#526572}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.scroll{{overflow:auto}}</style>
<main><header><p class="banner"><b>DEMO / SIMULATION</b> · 실제 공공 API 미연동 · 최종 운영 결정 없음</p><h1>Inventory & Risk Agent</h1><p>기준일 {esc(report['as_of'])} · 알림 {len(cards)}개 · 독립 대체 후보 {len(rows)}개</p><p>후보는 Decision Agent와 운영자의 검토 대상입니다. 영양 기준은 메뉴 한 가지에 대한 DEMO 설정이며, 전체 식사의 영양 적합성을 뜻하지 않습니다.</p></header>
<section><h2>발견된 이상</h2><ul>{''.join(cards)}</ul></section><section><h2>대체 메뉴 후보</h2><p>각 후보의 재고는 독립적으로 계산됩니다. 복수 후보를 함께 선택할 때는 재검증해야 합니다.</p><div class="scroll"><table><thead><tr><th>제공일</th><th>원래 메뉴</th><th>후보</th><th>영양</th><th>재고 가용</th><th>비용</th><th>검토 가능</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>재실행 요청</h2><p>{esc(', '.join(report['recommended_rechecks']) or '없음')}</p><h2>Decision Trace</h2><ol>{''.join('<li>'+esc(t)+'</li>' for t in report['decision_trace'])}</ol></section><section><details><summary>전체 구조화 보고서와 데이터 출처</summary><pre>{payload}</pre></details></section></main></html>'''
