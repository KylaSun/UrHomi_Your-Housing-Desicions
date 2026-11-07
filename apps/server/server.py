import json, sqlite3, secrets, os, argparse, re, math
import ai_service
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
ROOT=Path(__file__).resolve().parents[2]
DB=Path(os.environ.get('URHOMI_DB',str(ROOT/'data/urhomi.sqlite3')))
DECISIONS=['considering','shortlisted','passed','chosen']
ACTIONS=['replied','not_contacted','awaiting_reply','viewing_applying','completed']
def now(): return datetime.now(timezone.utc).isoformat()
def connect():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 DB.parent.mkdir(parents=True,exist_ok=True)
 with connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS homes (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, url TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(project_id,url))')
  if not c.execute('SELECT 1 FROM settings').fetchone():
   c.execute('INSERT INTO settings VALUES (1,?)',(json.dumps({'token':secrets.token_urlsafe(32),'projects':[{'id':'default','name':'我的留学住房项目','school':'','budget':None,'currency':'GBP','period':'week','room_type':'','move_in':''}]}),))
def settings():
 with connect() as c:return json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
def clean_url(value):
 u=urlsplit(str(value))
 if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:raise ValueError('请输入有效的 http/https 房源链接')
 site='rightmove' if u.hostname.lower() in ('rightmove.co.uk','www.rightmove.co.uk') else 'zoopla' if u.hostname.lower() in ('zoopla.co.uk','www.zoopla.co.uk') else ''
 match=re.fullmatch(r'/properties/(\d+)/?',u.path) if site=='rightmove' else re.fullmatch(r'/to-rent/details/(\d+)/?',u.path) if site=='zoopla' else None
 if match:return 'https://www.'+site+'.co.uk/'+('properties/' if site=='rightmove' else 'to-rent/details/')+match[1]+('/' if site=='zoopla' else '')
 return urlunsplit((u.scheme,u.netloc,u.path,u.query,''))
def optional_number(value, label, minimum=0, maximum=10000000):
 if value in ('',None):return None
 value=float(value)
 if not math.isfinite(value) or not minimum<=value<maximum:raise ValueError(label+'无效')
 return value

def valid_date(value):
 value=str(value or '')
 if value:
  try:datetime.strptime(value,'%Y-%m-%d')
  except ValueError:raise ValueError('日期格式应为 YYYY-MM-DD')
 return value

def fields(data):
 result={}
 for key in ['address','image_source','image_page_url','extracted_at','title','source','room_type','currency','period','available_from','tenancy','bills','notes','guarantor','students']:
  result[key]=str(data.get(key,'')).strip()[:4000]
 # Keep bounded page extraction provenance; never accept executable content.
 result['adapter']=data.get('adapter','') if data.get('adapter','') in ('','rightmove','zoopla','generic') else ''
 raw_sources=data.get('extraction_sources',{})
 result['extraction_sources']={k:{'source':str(v.get('source',''))[:100],'text':str(v.get('text',''))[:500]} for k,v in raw_sources.items() if k in ('price','available_from','tenancy','bills','students') and isinstance(v,dict)} if isinstance(raw_sources,dict) else {}
 warnings=data.get('extraction_warnings',[])
 result['extraction_warnings']=[str(v)[:500] for v in warnings[:8]] if isinstance(warnings,list) else []
 image=str(data.get('image_url') or '')[:2000]
 try:
  u=urlsplit(image)
  image=image if u.scheme=='https' and u.hostname and not u.username and not u.password else ''
 except ValueError:image=''
 result['images']=[]
 raw_images=data.get('images',[])
 for item in raw_images[:24] if isinstance(raw_images,list) else []:
  value=item.get('url','') if isinstance(item,dict) else item
  try:
   u=urlsplit(str(value));value=str(value)[:2000]
   if u.scheme=='https' and u.hostname and not u.username and not u.password and not any(x['url']==value for x in result['images']):result['images'].append({'url':value,'source':str(item.get('source','原房源相册'))[:100] if isinstance(item,dict) else '原房源相册'})
  except ValueError:pass
 result['image_url']=image
 result['bedrooms']=optional_number(data.get('bedrooms'),'卧室数',0,100)
 if result['bedrooms'] is not None and not result['bedrooms'].is_integer():raise ValueError('卧室数应为整数')
 result['rent_basis']=str(data.get('rent_basis',''))
 if result['rent_basis'] not in ('','whole','person'):raise ValueError('报价对象无效')
 for key,label in [('bills_monthly','每月账单'),('transport_monthly','每人交通费用'),('deposit','押金'),('prepaid_months','预付月数'),('tenancy_months','租期月数'),('commute_minutes','通勤分钟')]:
  result[key]=optional_number(data.get(key),label)
 result['available_from']=valid_date(result['available_from'])
 result['url']=clean_url(data.get('url',''))
 result['title']=result['title'] or '未命名房源'
 result['source']=result['source'] or urlsplit(result['url']).hostname
 if result['currency'] not in ('GBP','USD','EUR','CNY',''): raise ValueError('不支持的币种')
 if result['period'] not in ('week','month',''): raise ValueError('请选择每周或每月')
 for key in ('guarantor','students'):
  if result[key] not in ('','yes','no'):raise ValueError('申请条件无效')
 if result['bills'] not in ('','included','excluded'):raise ValueError('账单状态无效')
 price=data.get('price')
 result['price']=None if price in ('',None) else float(price)
 if result['price'] is not None and (not 0<result['price']<10000000): raise ValueError('价格必须是有效正数')
 return result
def analysis(h,p):
 known=h.get('price') is not None and bool(h.get('currency') and h.get('period'))
 rent=h['price']*(52/12 if h['period']=='week' else 1) if known else None
 party=int(p.get('party_size') or 1)
 divisor=party if h.get('rent_basis')=='whole' else 1
 basis_known=h.get('rent_basis')=='person' or p.get('party_size')==1 or (h.get('rent_basis')=='whole' and p.get('party_size') is not None)
 per_person=rent/divisor if rent is not None and basis_known else None
 bills=0 if h.get('bills')=='included' else h.get('bills_monthly')
 bills_person=bills/divisor if bills is not None and basis_known else None
 transport=h.get('transport_monthly')
 total=per_person+bills_person+transport if all(x is not None for x in (per_person,bills_person,transport)) else None
 upfront=h['deposit']+rent*h['prepaid_months'] if rent is not None and h.get('deposit') is not None and h.get('prepaid_months') is not None else None
 fit=[]
 def row(label,status,reason):fit.append({'label':label,'status':status,'reason':reason})
 budget=p.get('budget')
 if budget and per_person is not None and h.get('currency')==p.get('currency'):
  limit=budget*(52/12 if p.get('period')=='week' else 1)
  row('基础租金预算','conflict' if per_person>limit else 'matched',f'每人月租 {per_person:.2f}，预算 {limit:.2f}（均为 {h["currency"]}；不含额外费用）')
 else:row('基础租金预算','unknown','请补充预算、同币种报价及报价对象；多人时不自动假定均摊')
 if p.get('room_type') and h.get('room_type'):row('房型','matched' if p['room_type']==h['room_type'] else 'conflict','与已填写的房型偏好比较')
 else:row('房型','unknown','请填写房型偏好或核实房源房型')
 if p.get('move_in') and h.get('available_from'):row('入住日期','conflict' if h['available_from']>p['move_in'] else 'matched','房源可入住日期 '+h['available_from']+'；计划 '+p['move_in'])
 else:row('入住日期','unknown','可入住日期或计划日期尚未明确')
 row('留学生申请','matched' if h.get('students')=='yes' else 'conflict' if h.get('students')=='no' else 'unknown','接受国际学生' if h.get('students')=='yes' else '明确表示不接受国际学生' if h.get('students')=='no' else '需要向房东核实')
 if h.get('guarantor')=='no':row('英国担保人','matched','已填条件为不需要英国担保人')
 elif h.get('guarantor')=='yes' and p.get('has_guarantor') in ('yes','no'):row('英国担保人','matched' if p['has_guarantor']=='yes' else 'conflict','要求英国担保人；你的需求资料已填'+('有' if p['has_guarantor']=='yes' else '没有'))
 else:row('英国担保人','unknown','房源要求或个人担保条件尚未明确')
 if h.get('commute_minutes') is not None and p.get('max_commute') is not None:row('通勤','matched' if h['commute_minutes']<=p['max_commute'] else 'conflict','使用你手动核实的路线分钟数，未接地图服务')
 else:row('通勤','unknown','暂无已核实路线；可手动填写分钟数和接受上限')
 if h.get('tenancy_months') is not None and p.get('stay_months') is not None:row('租期','matched' if h['tenancy_months']<=p['stay_months'] else 'conflict','按已填最低租期和计划居住月数比较，具体合同待核实')
 else:row('租期','unknown','请补充最低租期月数和计划居住月数')
 gaps=[]
 if per_person is None:gaps.append('基础租金或报价对象')
 if bills_person is None:gaps.append('额外账单金额')
 if transport is None:gaps.append('每人交通费用')
 return {'fit':fit,'cost':{'rent_monthly':rent,'rent_person':per_person,'bills_person':bills_person,'transport_person':transport,'total_person':total,'upfront':upfront,'contract_person':total*h['tenancy_months'] if total is not None and h.get('tenancy_months') else None,'gaps':gaps,'divisor':divisor,'basis_known':basis_known}}

def assessment(h,p):
 missing=[label for field,label in [('price','价格'),('currency','币种'),('period','计价周期'),('room_type','房型'),('bills','账单'),('available_from','入住日期'),('tenancy','租期'),('guarantor','英国担保人'),('students','接受留学生')] if h.get(field) in ('',None)]
 conflicts=[]
 if any(r['label']=='基础租金预算' and r['status']=='conflict' for r in analysis(h,p)['fit']):conflicts.append('租金超出预算（未包含未知账单）')
 if p.get('room_type') and h.get('room_type') and p['room_type']!=h['room_type']:conflicts.append('房型与偏好不同')
 if p.get('move_in') and h.get('available_from') and h['available_from']>p['move_in']:conflicts.append('可入住日期晚于计划')
 due=bool(h.get('follow_up_at') and h['follow_up_at']<=now())
 if h.get('students')=='no':conflicts.append('房东表示不接受国际学生')
 if h.get('guarantor')=='yes' and p.get('has_guarantor')=='no':conflicts.append('英国担保人条件冲突')
 if h['decision_status']=='passed':next_step='已排除，可重新考虑'
 elif h['decision_status']=='chosen':next_step='已选定，继续处理后续事项'
 elif h['action_status']=='completed':next_step='当前流程已完成'
 elif h['action_status']=='viewing_applying':next_step='记录看房或申请进展'
 elif h['action_status']=='awaiting_reply':next_step='准备跟进' if due else '等待回复，可记录回复'
 elif h['action_status']=='replied':next_step='先核实已知条件冲突与可行替代方案' if conflicts else '已记录回复，继续核实未知条件或安排看房'
 elif h.get('last_response_at'):next_step='核实回复内容并更新房源信息'
 elif conflicts:next_step='检查条件冲突后决定是否联系'
 elif missing:next_step='咨询并核实缺失信息'
 else:next_step='比较候选或准备咨询'
 return {'missing':missing,'conflicts':conflicts,'due':due,'next_step':next_step,**analysis(h,p)}
QUESTIONS={
 'bills':('租金包含哪些账单？','Which bills are included, and what additional costs apply?'),
 'guarantor':('是否需要英国担保人？','Is a UK guarantor required, and are alternatives available?'),
 'students':('是否接受国际学生申请？','Do you accept international student applicants?'),
 'available_from':('何时可入住？','When is the property available?'),
 'tenancy':('最短租期和预付条件？','What are the minimum tenancy and upfront payment requirements?'),
 'sharing':('是否允许计划人数合租？','What are the occupancy and unrelated sharer requirements?'),
 'deposit':('押金及其他入住费用？','What deposit and other upfront costs are required?')}
REPLY_VALUES={'bills':['included','excluded'],'guarantor':['yes','no'],'students':['yes','no']}
def extract_reply(text):
 # Conservative local rules. Ambiguous or contradictory statements remain unknown.
 patterns={
 'bills':{'included':r'(?<!not )\bbills (?:are )?included\b|(?<!不)包(?:含)?水电', 'excluded':r'\bbills (?:are )?not included\b|\bbills excluded\b|不包(?:含)?水电'},
 'guarantor':{'yes':r'(?<!no )\b(?:a )?UK guarantor (?:is )?required\b|(?<!不)需要英国担保人','no':r'\bno UK guarantor (?:is )?required\b|\bUK guarantor (?:is )?not required\b|不需要英国担保人'},
 'students':{'yes':r'\b(?:international )?students (?:are )?(?:accepted|welcome)\b|(?<!不)接受国际学生','no':r'\bno (?:international )?students\b|\bstudents (?:are )?not accepted\b|不接受国际学生'}}
 text=' '.join(part for part in re.split(r'(?<=[.!?。！？])\s*|\n',text) if not re.search(r'[?？]|\b(?:if|maybe|might|unsure|not sure|not confirmed)\b|可能|是否|不确定',part,re.I))
 result={}
 for key,choices in patterns.items():
  found=[value for value,pattern in choices.items() if re.search(pattern,text,re.I)]
  if len(found)==1:result[key]=found[0]
 return result

def draft(h,followup=False):
 if followup:return 'Hi, I’m following up on my enquiry about '+h['title']+'. Is it still available? Thank you!'
 questions=[]
 for key,q in [('price','What is the rent?'),('period','Is the rent weekly or monthly?'),('bills','Are bills included, and what additional costs apply?'),('available_from','When is the property available?'),('tenancy','What is the minimum tenancy length?'),('room_type','Could you confirm the room type?')]:
  if h.get(key) in ('',None):questions.append(q)
 return 'Hi, I’m interested in '+h['title']+'. Is it still available? '+ ' '.join(questions)+' Could you let me know the next steps for a viewing? Thank you!'
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,data):
  body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
  self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
 def do_GET(self):
  try:
   if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):return self.send(403,{'error':'Host rejected'})
   if self.path=='/api/bootstrap':return self.send(200,{**settings(),'ai':ai_service.status()})
   if self.path=='/api/ai/status':return self.send(200,ai_service.status())
   if self.path=='/api/homes':
    s=settings(); projects={p['id']:p for p in s['projects']}
    with connect() as c:homes=[json.loads(r[0]) for r in c.execute('SELECT data FROM homes ORDER BY rowid DESC')]
    for h in homes:
     h['assessment']=assessment(h,projects[h['project_id']])
     h['ai_brief_stale']=bool(h.get('ai_brief') and h['ai_brief'].get('fingerprint')!=ai_service.fingerprint(h,projects[h['project_id']]))
    return self.send(200,homes)
   if self.path in ('/integration-test','/integration-tests.js'):
    name='integration.html' if self.path=='/integration-test' else 'integration-tests.js'
    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8' if name.endswith('html') else 'text/javascript; charset=utf-8');self.end_headers();self.wfile.write((ROOT/'tests'/name).read_bytes());return
   if self.path in ('/panel','/panel.js','/panel.css','/extract.js'):
    name={'/panel':'panel.html'}.get(self.path,self.path[1:]);file=ROOT/'apps/extension'/name
    self.send_response(200);self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css'}[file.suffix[1:]]);self.end_headers();self.wfile.write(file.read_bytes());return
   path={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/fixture':'fixture.html'}.get(self.path)
   if not path:return self.send(404,{'error':'Not found'})
   file=ROOT/'apps/web'/path
   self.send_response(200);self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css'}[file.suffix[1:]])
   self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' https:; object-src 'none'; frame-ancestors 'none'")
   self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(file.read_bytes())
  except Exception:self.send(500,{'error':'读取失败'})
 def do_POST(self):
  try:
   if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):return self.send(403,{'error':'Host rejected'})
   if self.headers.get('Authorization')!='Bearer '+settings()['token']:return self.send(403,{'error':'连接密钥无效，请从网页设置中复制'})
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<=64000:raise ValueError('请求大小无效')
   d=json.loads(self.rfile.read(n));s=settings()
   if self.path=='/api/ai/config':return self.send(200,ai_service.configure(d))
   if self.path=='/api/ai/test':return self.send(200,ai_service.test_connection())
   if self.path in ('/api/ai/enquiry','/api/ai/reply','/api/ai/brief'):
    ident=str(d.get('id',''))
    with connect() as c:row=c.execute('SELECT data FROM homes WHERE id=?',(ident,)).fetchone()
    if not row:return self.send(404,{'error':'房源不存在'})
    original=json.loads(row[0]);project=next(p for p in s['projects'] if p['id']==original['project_id'])
    if self.path=='/api/ai/enquiry':
     selected=d.get('questions',[])
     if not isinstance(selected,list) or not selected or any(q not in QUESTIONS for q in selected) or len(selected)>len(QUESTIONS):raise ValueError('请勾选有效的咨询问题')
     tone=d.get('tone','friendly')
     if tone not in ('friendly','formal'):raise ValueError('语气选项无效')
     return self.send(200,ai_service.enquire(original,project,[{'zh':QUESTIONS[q][0],'en':QUESTIONS[q][1]} for q in selected],tone,original.get('contacted_at')))
    if self.path=='/api/ai/reply':
     text=str(d.get('text','')).strip()
     if not text or len(text)>8000:raise ValueError('回复应为 1–8000 字')
     result=ai_service.extract(text);event='ai_extract_reply'
    else:result=ai_service.brief(original,project,assessment(original,project));event='ai_brief'
    with connect() as c:
     c.execute('BEGIN IMMEDIATE')
     current_row=c.execute('SELECT data FROM homes WHERE id=?',(ident,)).fetchone()
     if not current_row:return self.send(409,{'error':'房源已被删除，请刷新'})
     h=json.loads(current_row[0])
     current_project=next(p for p in settings()['projects'] if p['id']==h['project_id'])
     if h['updated_at']!=original['updated_at'] or ai_service.fingerprint(h,current_project)!=ai_service.fingerprint(original,project):return self.send(409,{'error':'房源或需求已更新，本次 AI 结果未写入，请刷新后重试'})
     stamp=now()
     if event=='ai_extract_reply':h['pending_reply']={'text':text,'fields':result['fields'],'evidence':result['evidence'],'summary_zh':result['summary_zh'],'engine':result['engine'],'model':result['model'],'at':stamp}
     else:h['ai_brief']={**result,'at':stamp}
     h['history'].append({'at':stamp,'event':event,'engine':result['engine'],'model':result['model']});h['updated_at']=stamp
     c.execute('UPDATE homes SET data=? WHERE id=?',(json.dumps(h),ident))
    return self.send(200,{'home':h,'result':result})
   if self.path=='/api/demo':
    existing=next((p for p in s['projects'] if p.get('is_demo')),None)
    if existing:return self.send(200,{'project_id':existing['id'],'existing':True})
    demo={'id':secrets.token_hex(8),'name':'流程演练 · 合成数据','is_demo':True,'school':'演练校区（非真实学校）','budget':1200,'currency':'GBP','period':'month','room_type':'studio','move_in':'2027-09-01','party_size':1,'has_guarantor':'no','max_commute':40,'stay_months':12}
    s['projects'].append(demo)
    with connect() as c:
     c.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(s),))
     for suffix,title,price,bills in [('a','演练房源 A · Studio（合成）',1050,''),('b','演练房源 B · Studio（合成）',1150,'included')]:
      h=fields({'title':title,'url':'https://example.org/urhomi-demo/'+suffix,'source':'流程演练 · 非真实房源','price':price,'currency':'GBP','period':'month','room_type':'studio','bills':bills,'rent_basis':'person','available_from':'2027-08-25','tenancy_months':12,'transport_monthly':60})
      h.update(id=secrets.token_hex(8),project_id=demo['id'],decision_status='considering',action_status='not_contacted',created_at=now(),updated_at=now(),draft='',contacted_at=None,last_response_at=None,follow_up_at=None,history=[])
      c.execute('INSERT INTO homes VALUES (?,?,?,?)',(h['id'],demo['id'],h['url'],json.dumps(h)))
    return self.send(201,{'project_id':demo['id'],'existing':False})
   if self.path=='/api/workspace':
    pid=str(d.get('project_id',''))
    if pid not in [p['id'] for p in s['projects']]:raise ValueError('请选择有效项目')
    allowed={'area':100,'area_notes':4000,'display_name':80,'bio':1000,'lifestyle':1000,'campus_draft':4000,'roommates_draft':4000,'nearby_draft':4000}
    incoming=d.get('fields',{})
    if not isinstance(incoming,dict) or any(k not in allowed for k in incoming):raise ValueError('资料字段无效')
    with connect() as c:
     current=json.loads(c.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
     entry=current.setdefault('workspace',{}).setdefault(pid,{})
     for key,value in incoming.items():
      if not isinstance(value,str) or len(value)>allowed[key]:raise ValueError('内容过长或格式无效')
      entry[key]=value.strip()
     c.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(current),))
    return self.send(200,entry)
   if self.path=='/api/projects':
    p={'id':d.get('id') or secrets.token_hex(8),'name':str(d.get('name','')).strip()[:100],'school':str(d.get('school',''))[:200],'budget':None if d.get('budget') in ('',None) else float(d['budget']),'currency':d.get('currency','GBP'),'period':d.get('period','week'),'room_type':str(d.get('room_type',''))[:80],'move_in':str(d.get('move_in',''))}
    if not p['name'] or p['currency'] not in ('GBP','USD','EUR','CNY') or p['period'] not in ('week','month') or (p['budget'] is not None and not 0<p['budget']<10000000):raise ValueError('项目名称、预算或计价单位无效')
    old=next((x for x in s['projects'] if x['id']==p['id']),{})
    p={**old,**p,'party_size':int(float(d.get('party_size',old.get('party_size',1)))),'has_guarantor':d.get('has_guarantor',old.get('has_guarantor','')),'max_commute':optional_number(d.get('max_commute',old.get('max_commute')),'通勤上限'),'stay_months':optional_number(d.get('stay_months',old.get('stay_months')),'计划居住月数',0.01)}
    p['move_in']=valid_date(p['move_in'])
    if float(d.get('party_size',old.get('party_size',1)))!=p['party_size']:raise ValueError('合租人数应为整数')
    if not 1<=p['party_size']<=20 or p['has_guarantor'] not in ('','yes','no'):raise ValueError('合租人数或担保人选项无效')
    s['projects']=[x for x in s['projects'] if x['id']!=p['id']]+[p]
    with connect() as c:c.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(s),))
    return self.send(200,p)
   if self.path=='/api/homes':
    h=fields(d);pid=d.get('project_id')
    if pid not in [p['id'] for p in s['projects']]:raise ValueError('请选择有效项目')
    h.update(id=secrets.token_hex(8),project_id=pid,decision_status='considering',action_status='not_contacted',created_at=now(),updated_at=now(),draft='',contacted_at=None,last_response_at=None,follow_up_at=None,history=[])
    with connect() as c:
     c.execute('BEGIN IMMEDIATE')
     # Also recognize records created before canonical listing identities existed.
     old=next((r for r in c.execute('SELECT data FROM homes WHERE project_id=?',(pid,)) if clean_url(json.loads(r[0])['url'])==h['url']),None)
     if old:return self.send(200,{'home':json.loads(old[0]),'duplicate':True})
     c.execute('INSERT INTO homes VALUES (?,?,?,?)',(h['id'],pid,h['url'],json.dumps(h)))
    return self.send(201,{'home':h,'duplicate':False})
   if self.path.startswith('/api/homes/'):
    ident=self.path.rsplit('/',1)[1]
    with connect() as c:
     row=c.execute('SELECT data FROM homes WHERE id=?',(ident,)).fetchone()
     if not row:return self.send(404,{'error':'房源不存在'})
     h=json.loads(row[0]);event=d.get('event');entry={'at':now(),'event':event}
     if event=='edit':
      updated=fields({**h,**d})
      for key in REPLY_VALUES:
       if updated.get(key)!=h.get(key) and key in h.get('field_sources',{}):
        h['field_sources'][key]={'source':'用户手动修改','text':updated[key] or '已清空，待核实','at':now()}
      h.update(updated)
     elif event=='refresh_media':
      updated=fields({**h,**d})
      for key in ['images','image_url','image_source','image_page_url','extracted_at']:h[key]=updated[key]
      for key in ['address','bedrooms']:
       if h.get(key) in ('',None):h[key]=updated[key]
     elif event=='progress':
      if d.get('value') not in ('viewing_applying','completed'):raise ValueError('进展选项无效')
      h['action_status']=d['value'];h['follow_up_at']=None;entry['value']=d['value']
     elif event=='decision':
      if d.get('value') not in DECISIONS:raise ValueError('决策状态无效')
      h['decision_status']=d['value'];entry['value']=d['value']
     elif event=='prepare':h['draft']=draft(h,d.get('followup',False))
     elif event=='draft':
      h['draft']=str(d.get('text',''))[:8000]
      if 'questions' in d:
       if not isinstance(d['questions'],list) or any(q not in QUESTIONS for q in d['questions']):raise ValueError('问题无效')
       h['questions']=d['questions']
     elif event=='contact':
      if not str(d.get('text','')).strip():raise ValueError('请先准备咨询消息')
      days=d.get('days')
      if days not in (0,2,3,5):raise ValueError('跟进时间无效')
      h.update(draft=str(d['text'])[:8000],contacted_at=now(),action_status='awaiting_reply',follow_up_at=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat() if days else None)
      entry['text']=h['draft']
     elif event=='reply':
      text=str(d.get('text','')).strip()[:8000]
      if not text:raise ValueError('请填写回复或进展')
      action=d.get('action','not_contacted')
      if action not in ACTIONS:raise ValueError('联系状态无效')
      h.update(last_response_at=now(),follow_up_at=None,action_status=action);entry['text']=text
     elif event=='extract_reply':
      text=str(d.get('text','')).strip()[:8000]
      if not text:raise ValueError('请粘贴房东回复')
      h['pending_reply']={'text':text,'fields':extract_reply(text),'at':now()}
     elif event=='confirm_reply':
      pending=h.get('pending_reply')
      if not pending:raise ValueError('请先提取回复')
      approved=d.get('fields',{})
      if not isinstance(approved,dict) or not approved:raise ValueError('请选择至少一个明确字段，或只保存原文')
      for key,value in approved.items():
       if key not in pending['fields'] or value!=pending['fields'][key]:raise ValueError('回复字段无效')
      h.update(approved);h.update(last_response_at=now(),follow_up_at=None,action_status='replied')
      h.setdefault('field_sources',{}).update({key:{'source':'房东回复，用户提供并确认','text':pending['text'],'at':now(),'evidence':pending.get('evidence',{}).get(key),'engine':pending.get('engine','rules')} for key in approved})
      entry.update(text=pending['text'],fields=approved);h['pending_reply']=None
     elif event=='reply_text':
      pending=h.get('pending_reply')
      if not pending:raise ValueError('请先录入回复')
      entry['text']=pending['text'];h.update(pending_reply=None,last_response_at=now(),follow_up_at=None,action_status='replied')
     elif event=='delete':
      c.execute('DELETE FROM homes WHERE id=?',(ident,));return self.send(200,{'deleted':True})
     else:raise ValueError('操作无效')
     h['updated_at']=now();h['history'].append(entry)
     c.execute('UPDATE homes SET url=?,data=? WHERE id=?',(h['url'],json.dumps(h),ident))
    return self.send(200,h)
   return self.send(404,{'error':'Not found'})
  except (ValueError,TypeError,KeyError,sqlite3.IntegrityError) as e:self.send(400,{'error':str(e)})
  except Exception:self.send(500,{'error':'保存失败，请重试'})
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args();init()
 print(f'UrHomi: http://127.0.0.1:{args.port}',flush=True)
 ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
