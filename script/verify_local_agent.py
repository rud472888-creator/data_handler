"""Real local model + isolated generated-media workflow. No external messages."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    workspace = Path(__file__).resolve().parents[1]
    root = Path(tempfile.mkdtemp(prefix='local-llm-', dir=workspace / '.pipeline'))
    os.environ['DATA_HANDLER_PIPELINE_ROOT'] = str(root)
    os.environ['PYTHONPATH'] = str(workspace)
    os.environ['HF_HUB_OFFLINE'] = '1'
    from orchestrator.agent.service import AgentService
    from orchestrator.dit_app.server import card_snapshot
    config = json.loads((Path.home() / 'Library/Application Support/Data Handler/.pipeline/agent/config.json').read_text())
    config['allowed_roots'] = [str(root)]
    service = AgentService(root, config)
    service.registry.save({'projects':[{'id':'qa', 'name':'Local LLM QA', 'replica_roots':[],
        'replica_project_roots':[], 'preset_name':'dit', 'created_at':'', 'updated_at':''}], 'runs':[]})
    source, first, second = [root / name for name in ('card','replica-one','replica-two')]
    for path in (source, first, second):
        path.mkdir()
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=320x240:r=24',
                    '-t','0.25','-c:v','libx264','-pix_fmt','yuv420p',str(source/'A001.mp4')],check=True)
    history = []
    transcript = []
    messages = ['선택한 프로젝트의 카드를 두 곳에 복제하고 싶어. 필요한 정보를 물어봐.',
                f'원본은 {source}야.', f'복제 위치는 {first} 및 {second}야. 오늘 촬영, 카메라 A로 계획을 만들어줘.']
    for message in messages:
        started = time.monotonic()
        result = service.interpret(message, 'qa', history=history, project_id='qa')
        transcript.append({'request':message,'response':result,'seconds':round(time.monotonic()-started,2)})
        (root/'transcript.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2))
        history += [{'role':'user','text':message},{'role':'assistant','text':result['text']}]
        print('Model turn completed:',len(transcript),'plan' if 'plan' in result else 'clarification',flush=True)
    plan = result['plan']
    assert plan['project_id'] == 'qa'
    assert plan['source_path'] == str(source)
    assert plan['replica_paths'] == [str(first),str(second)]
    print('Confirmed isolated fixture plan:',plan['project_name'],plan['source_path'],plan['destinations'],flush=True)
    execution = service.execute(plan['id'],'qa')
    folder = root/'runs'/execution['run_id']
    deadline = time.monotonic()+90
    while not (folder/'events/datahelper.done.json').exists() and time.monotonic()<deadline:
        time.sleep(.5)
    record = next(r for r in service.registry.load()['runs'] if r['run_id']==execution['run_id'])
    card = card_snapshot(record,root/'runs')
    assert card['phase']=='reported', card
    expected = hashlib.sha256((source/'A001.mp4').read_bytes()).hexdigest()
    for destination in plan['destinations']:
        assert hashlib.sha256((Path(destination)/'A001.mp4').read_bytes()).hexdigest()==expected
    pdfs = [a for a in card['artifacts'] if a['path'].endswith('.pdf')]
    assert len(pdfs)>=3 and all(Path(a['path']).read_bytes().startswith(b'%PDF') for a in pdfs)
    evidence = {'ok':True,'model_turns':len(transcript),'run_id':execution['run_id'],
                'phase':card['phase'],'pdf_count':len(pdfs),'sha256':expected,'network_for_inference':'loopback only'}
    (root/'result.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence),flush=True)
    print('Evidence:',root,flush=True)


if __name__ == '__main__':
    main()
