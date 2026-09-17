import json
from pathlib import Path
from lastplate_decision.agents.decision import make_final_recommendation
from examples.fixtures import baseline


def main():
    payload = baseline()
    payload['inventory_risk_result']['is_demo'] = True
    payload['inventory_risk_result']['data_quality_notes'] = ['모든 입력은 테스트용 합성 DEMO입니다.']
    result = make_final_recommendation(**payload)
    folder = Path(__file__).parent
    (folder / 'demo_input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'demo_output.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
