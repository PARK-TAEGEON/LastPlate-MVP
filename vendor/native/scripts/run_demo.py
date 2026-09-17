import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integration import run_lastplate_pipeline,PipelineConfig
parser=argparse.ArgumentParser()
parser.add_argument('input',type=Path)
parser.add_argument('--storage',type=Path,default=Path('runtime'))
parser.add_argument('--output',type=Path)
args=parser.parse_args()
result=run_lastplate_pipeline(json.loads(args.input.read_text(encoding='utf-8')),config=PipelineConfig(storage_dir=args.storage.resolve()))
text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
if args.output:
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(text,encoding='utf-8')
print(json.dumps({k:result[k] for k in ('pipeline_status','errors','warnings','timings')},ensure_ascii=False,indent=2))
if result['decision']: print(result['decision']['decision_type'])
