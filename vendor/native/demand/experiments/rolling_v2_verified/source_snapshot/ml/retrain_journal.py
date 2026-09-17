"""Durable evaluation ledger. Consumed dates stay burned even after failures."""
import contextlib
import json
import sqlite3
from pathlib import Path
from .service_store import canonical
from .model_registry import atomic_json

class RetrainJournal:
    def __init__(self,models):
        self.path=Path(models)/'retrain.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,state TEXT NOT NULL,document TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS consumed_dates(date TEXT PRIMARY KEY,run_id TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def connect(self):
        with sqlite3.connect(self.path,timeout=10) as db:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            yield db

    def used_dates(self):
        with self.connect() as db:
            return {r[0] for r in db.execute('SELECT date FROM consumed_dates')}

    def reserve(self,run_id,dates,document):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO runs VALUES (?,?,?)',(run_id,'reserved',canonical(document)))
            db.executemany('INSERT INTO consumed_dates VALUES (?,?)',[(d,run_id) for d in dates])

    def update(self,run_id,state,document):
        with self.connect() as db:
            db.execute('UPDATE runs SET state=?,document=? WHERE id=?',(state,canonical(document),run_id))

    def runs(self):
        with self.connect() as db:
            return [dict(id=r['id'],state=r['state'],document=json.loads(r['document'])) for r in db.execute('SELECT * FROM runs ORDER BY rowid')]

    def export(self,run,report_dir):
        """SQLite is authoritative; reports are repeatable materialized views."""
        import pandas as pd
        out=Path(report_dir);out.mkdir(parents=True,exist_ok=True)
        atomic_json(out/(run['id']+'.json'),run)
        rows=run['document'].get('predictions')
        if rows is not None:
            temp=out/(run['id']+'.csv.tmp')
            pd.DataFrame(rows).to_csv(temp,index=False)
            temp.replace(out/(run['id']+'.csv'))

    def recover(self,registry,report_dir):
        results=[]
        for run in self.runs():
            state=run['state'];doc=run['document'];version=doc.get('candidate_version')
            if state=='reserved':
                state='interrupted';doc['recovery']='No completed evaluation; gate remains consumed'
            elif state in ('evaluated','prepared'):
                if doc.get('accepted') and version and (registry.path/'releases'/version/'metadata.json').exists():
                    try:
                        registry.activate(version,doc['incumbent_version'])
                        state='committed';doc['status']='promoted'
                    except RuntimeError:
                        state='conflict';doc['status']='incumbent_changed'
                elif not doc.get('accepted'):
                    state='kept';doc['status']='kept_incumbent'
                else:
                    state='interrupted';doc['recovery']='No complete refit artifact; gate remains consumed'
            self.update(run['id'],state,doc)
            run.update(state=state,document=doc)
            self.export(run,report_dir)
            results.append(run)
        return results
