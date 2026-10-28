import argparse,functools,http.server,json,os,shutil,subprocess,threading,time,traceback
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[3])
parser.add_argument('--work',type=Path,required=True)
parser.add_argument('--seconds',type=int,default=480)
parser.add_argument('--reverse-decks',action='store_true')
args=parser.parse_args()
work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
source=args.source.resolve()
site=source/'web/neoforge/dist'

java=Path(shutil.which('java')).parent
cp=os.environ['FORGE_BRIDGE_CLASSPATH']
classes=work/'classes';classes.mkdir(exist_ok=True)
profile=work/'profile';profile.mkdir(exist_ok=True)
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
(work/'source-revision.txt').write_text(revision+'\n')
with (work/'compile.log').open('w') as log:
 subprocess.run([str(java/'javac'),'-cp',cp,'-d',str(classes),str(source/'tools/browser-bridge/src/forge/browser/Bridge.java')],stdout=log,stderr=subprocess.STDOUT,check=True)
class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*_):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(site)))
threading.Thread(target=server.serve_forever,daemon=True).start()
origin=f'http://127.0.0.1:{server.server_port}'
log=(work/'engine.log').open('w+')
process=subprocess.Popen([str(java/'java'),'-Duser.home='+str(profile),'-cp',str(classes)+':'+cp,'forge.browser.Bridge',origin],cwd=source/'forge-gui-desktop',stdout=log,stderr=subprocess.STDOUT)
state={'snapshot':None,'errors':[],'actions':0,'status':'running'}
events=(work/'events.jsonl').open('w')
def event(kind,**data):
 events.write(json.dumps({'at':time.time(),'event':kind,**data},ensure_ascii=False)+'\n');events.flush()
def summary(s):return {'revision':s.get('revision'),'status':s.get('status'),'turn':s.get('turn'),'phase':s.get('phase'),'players':[{k:p.get(k) for k in ['name','life','handCount','libraryCount']} for p in s.get('players',[])],'prompt':s.get('prompt'),'result':s.get('result')}
try:
 token=None
 for _ in range(100):
  time.sleep(.1);log.flush();log.seek(0)
  for line in log:
   if line.startswith('Pairing token: '):token=line.split(': ',1)[1].strip()
  if token:break
  if process.poll() is not None:raise RuntimeError('Bridge stopped during startup')
 if not token:raise RuntimeError('Bridge startup timeout')
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH',shutil.which('chromium')),headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1440,'height':1000})
  page.set_default_timeout(3000)
  page.on('pageerror',lambda error:state['errors'].append(str(error)))
  def response(r):
   if '/api/v1/' not in r.url:return
   try:
    data=r.json()
    if 'players' in data:
     state['snapshot']=data
     event('snapshot',snapshot=data)
    elif r.status>=400:event('http_error',status=r.status,body=data)
   except Exception as e:event('response_error',error=str(e))
  def request(r):
   if '/api/v1/action' in r.url and r.method=='POST':
    payload=r.post_data_json
    assert payload.get('kind')!='concede'
    state['actions']+=1;event('action',payload=payload)
  page.on('response',response);page.on('request',request)
  page.goto(origin)
  page.locator('[data-action="stocks"]').click()
  stocks=page.locator('[data-stock]')
  assert stocks.count()>=2
  stocks.nth(0).click();stocks.nth(1).click()
  page.locator('#dialog-content [data-action="close"]').click()
  page.locator('[data-action="connect"]').click()
  page.locator('#host-token').fill(token)
  page.locator('[data-action="pair"]').click()
  expect(page.locator('#dialog')).not_to_be_visible()
  page.locator('[data-nav="play"]').click()
  decks=page.locator('#ai-deck option')
  if args.reverse_decks:
   page.locator('#human-deck').select_option(decks.nth(1).get_attribute('value'))
  else:page.locator('#ai-deck').select_option(decks.nth(1).get_attribute('value'))
  page.locator('[data-action="start"]').click()
  deadline=time.monotonic()+args.seconds
  seen=None;played_turns=set();attempts={};last_progress=time.monotonic();last_action=time.monotonic()
  while time.monotonic()<deadline:
   page.wait_for_timeout(60)
   s=state['snapshot']
   if not s:continue
   if s.get('status')=='error':raise RuntimeError('Engine error: '+str(s.get('error')))
   if s.get('status')=='finished':
    page.wait_for_timeout(300)
    assert s.get('result'), 'Natural terminal snapshot lacks authoritative result'
    assert all(x.get('lossReason')!='Conceded' for x in s['result']['participants']), 'Concession is not natural completion'
    expect(page.locator('.game-result')).to_be_visible()
    expect(page.locator('[data-prompt-button], [data-card], [data-player], [data-action=concede]')).to_have_count(0)
    assert 'Action failed' not in page.locator('body').inner_text()
    state['status']='finished';(work/'terminal.json').write_text(json.dumps(s,indent=2,ensure_ascii=False));page.screenshot(path=str(work/'terminal.png'),full_page=True);event('terminal_ui',text=page.locator('#app').inner_text());break
   prompt=s.get('prompt')
   if not prompt:continue
   rev=s.get('revision')
   if rev==seen:
    if time.monotonic()-last_action>30:raise RuntimeError('No prompt progress for 30 seconds: '+json.dumps(summary(s)))
    continue
   seen=rev
   if time.monotonic()-last_progress>25:
    print(json.dumps({'progress':summary(s),'actions':state['actions']},ensure_ascii=False),flush=True);last_progress=time.monotonic()
   kind=prompt['kind'];pid=prompt['id']
   try:
    if kind in ['priority','confirm']:
     human=next((x for x in s.get('players',[]) if x['name']=='You'),None)
     turn=s.get('turn')
     if kind=='priority' and human and s.get('activePlayerId')==human['id'] and s.get('phase')=='MAIN1' and turn not in played_turns:
      lands=[x for x in human.get('hand',[]) if 'Land' in x.get('type','')]
      played_turns.add(turn)
      if lands:
       page.locator('[data-card="'+lands[0]['id']+'"]').click();last_action=time.monotonic();continue
     buttons=prompt.get('buttons',[])
     enabled=[b for b in buttons if b.get('enabled')]
     keep=next((b for b in enabled if 'keep' in b.get('label','').lower()),None)
     alpha=next((b for b in enabled if b.get('label','').lower().replace(' ','')=='alphastrike'),None)
     button=keep or alpha or next((b for b in enabled if b['id']=='ok'),None) or next(iter(enabled),None)
     if button:page.locator('[data-prompt-button="'+button['id']+'"]').click()
     else:
      hand=human.get('hand',[]) if human else []
      done=attempts.setdefault(pid,set())
      candidate=next((c for c in hand if c['id'] not in done),None)
      if candidate:
       done.add(candidate['id']);page.locator('[data-card="'+candidate['id']+'"]').click()
      else:raise RuntimeError('No enabled button or untried hand card: '+json.dumps(summary(s)))
    elif kind in ['choices','order']:
     needed=max(0,prompt.get('min',0));choices=page.locator('input[name="choice"]')
     for i in range(needed):choices.nth(i).check()
     page.locator('[data-action="submit-choice"]').click()
    elif kind=='reveal':page.locator('[data-prompt-button="ok"]').click()
    elif kind=='manipulate':page.get_by_role('button',name='Confirm order',exact=True).click()
    elif kind=='input':
     if prompt.get('options')==[]:page.locator('[data-action="cancel-input"]').click()
     else:page.get_by_role('button',name='Confirm response',exact=True).click()
    elif kind=='allocation':
     targets=prompt['targets'];total=prompt['total'];amounts=[t['min'] for t in targets];remaining=total-sum(amounts)
     for i,t in enumerate(targets):
      give=min(remaining,t['max']-amounts[i]);amounts[i]+=give;remaining-=give
     assert remaining==0
     for i,amount in enumerate(amounts):page.locator('[name="allocation"]').nth(i).fill(str(amount))
     page.get_by_role('button',name='Confirm assignment',exact=True).click()
    else:raise RuntimeError('Unsupported prompt kind: '+str(kind))
    last_action=time.monotonic()
   except Exception as e:
    if 'No enabled button' in str(e) or 'Unsupported prompt' in str(e):raise
    event('ui_retry',error=str(e),snapshot=summary(s));seen=None;page.wait_for_timeout(100)
  else:raise TimeoutError('Natural-game probe exceeded its bounded run')
  (work/'final.json').write_text(json.dumps({'status':state['status'],'actions':state['actions'],'errors':state['errors'],'snapshot':state['snapshot']},indent=2,ensure_ascii=False))
  assert not state['errors'],state['errors']
  print(json.dumps({'status':state['status'],'actions':state['actions'],'terminal':summary(state['snapshot'])},ensure_ascii=False),flush=True)
  browser.close()
except Exception as e:
 state['status']='blocked';event('failure',error=str(e),traceback=traceback.format_exc())
 (work/'failure.json').write_text(json.dumps({'error':str(e),'actions':state['actions'],'snapshot':state['snapshot'],'page_errors':state['errors']},indent=2,ensure_ascii=False))
 print('BLOCKED '+str(e),flush=True)
 raise
finally:
 process.terminate()
 try:process.wait(timeout=8)
 except subprocess.TimeoutExpired:process.kill();process.wait()
 log.close();events.close();server.shutdown();server.server_close()
 text=(work/'engine.log').read_text(errors='replace')
 text='\n'.join('Pairing token: [REDACTED_SECRET]' if line.startswith('Pairing token: ') else line for line in text.splitlines())+'\n'
 (work/'engine.log').write_text(text)
