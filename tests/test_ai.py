import importlib.util,json,os,sys,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/server'))
import ai_service as ai
spec=importlib.util.spec_from_file_location('ai_test_server',ROOT/'apps/server/server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
FAKE_KEY='sk-test-only-not-a-real-api-key-1234567890'
def response(data,status='completed'):
 return {'status':status,'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data)}]}],'usage':{'total_tokens':25}}
class AIUnit(unittest.TestCase):
 def setUp(self):
  self.saved=(ai._key,ai._model,ai._enabled,ai._last_test);ai._key='';ai._enabled=False;ai._last_test=None
  self.env=patch.dict(os.environ,{'OPENAI_API_KEY':''});self.env.start()
 def tearDown(self):
  ai._key,ai._model,ai._enabled,ai._last_test=self.saved;self.env.stop()
 def enable(self):return ai.configure({'api_key':FAKE_KEY,'model':'gpt-5-mini','enabled':True,'consent':True})
 def test_enquiry_only_uses_verified_listing_fields(self):
  h={'price':1000,'students':'yes','bills':'included','field_sources':{'bills':{'source':'房东回复，用户提供并确认'},'students':{'source':'页面提取'}}}
  self.assertEqual({'bills':'included'},ai.enquiry_context(h,{})['listing'])
 def test_config_consent_and_no_secret_echo(self):
  with self.assertRaises(ai.AIError):ai.configure({'api_key':FAKE_KEY,'enabled':True})
  self.assertFalse(ai.status()['configured']);self.enable();self.assertNotIn(FAKE_KEY,json.dumps(ai.status()))
  ai.configure({'clear':True});self.assertFalse(ai.status()['enabled']);self.assertEqual('',ai._key)
 def test_minimized_context_and_no_provider_storage(self):
  self.enable();h={'title':'TEST ONLY','notes':'PRIVATE NOTES','history':['PRIVATE HISTORY'],'draft':'PRIVATE DRAFT','url':'https://private.example'};p={'budget':1000,'school':'PRIVATE CAMPUS','name':'PRIVATE NAME'}
  with patch.object(ai,'_transport',return_value=response({'message_en':'Hello, are bills included?','notes_zh':'仅测试'})) as transport:
   result=ai.enquire(h,p,[{'en':'Are bills included?'}],'friendly');payload,key=transport.call_args.args
  self.assertEqual(FAKE_KEY,key);self.assertFalse(payload['store']);self.assertNotIn('PRIVATE',json.dumps(payload));self.assertEqual('openai',result['engine']);self.assertNotIn(FAKE_KEY,json.dumps(result))
 def test_extraction_requires_literal_evidence_and_valid_values(self):
  self.enable();text='Utilities are extra. International students may apply.'
  good={'summary_zh':'测试摘要','fields':[{'field':'bills','value':'excluded','evidence':'Utilities are extra.'}]}
  with patch.object(ai,'_transport',return_value=response(good)):self.assertEqual({'bills':'excluded'},ai.extract(text)['fields'])
  for fields in ([{'field':'bills','value':'yes','evidence':'Utilities are extra.'}],[{'field':'guarantor','value':'yes','evidence':'This is not in source'}],[{'field':'bills','value':'excluded','evidence':'Utilities are extra.'}]*2):
   with self.subTest(fields=fields),patch.object(ai,'_transport',return_value=response({'summary_zh':'测试','fields':fields})),self.assertRaises(ai.AIError):ai.extract(text)
 def test_refusal_incomplete_and_busy(self):
  self.enable()
  for result in (response({},'incomplete'),{'status':'completed','output':[{'content':[{'type':'refusal','refusal':'No'}]}]},response(['not an object'])):
   with self.subTest(result=result),patch.object(ai,'_transport',return_value=result),self.assertRaises(ai.AIError):ai.enquire({}, {},['q'],'friendly')
  ai._gate.acquire()
  try:
   with self.assertRaises(ai.AIError):ai.enquire({}, {},['q'],'friendly')
  finally:ai._gate.release()
 def test_provider_error_is_sanitized(self):
  self.enable()
  error=urllib.error.HTTPError(ai.ENDPOINT,401,FAKE_KEY,{},None)
  with patch('urllib.request.OpenerDirector.open',side_effect=error),self.assertRaises(ai.AIError) as result:ai.test_connection()
  self.assertNotIn(FAKE_KEY,str(result.exception));self.assertIn('密钥无效',str(result.exception))
class AIHTTP(unittest.TestCase):
 enable=AIUnit.enable
 def setUp(self):
  AIUnit.setUp(self);self.tmp=tempfile.TemporaryDirectory();self.old_db=server.DB;server.DB=Path(self.tmp.name)/'test.sqlite3';server.init()
  self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.http.server_port);self.token=self.req('bootstrap')['token']
 def tearDown(self):
  self.http.shutdown();self.http.server_close();self.thread.join();server.DB=self.old_db;self.tmp.cleanup();AIUnit.tearDown(self)
 def req(self,path,data=None,auth=True):
  request=urllib.request.Request(self.base+'/api/'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+self.token} if auth and hasattr(self,'token') else {})})
  with urllib.request.urlopen(request) as r:return json.load(r)
 def home(self,suffix):return self.req('homes',{'project_id':'default','url':'https://example.org/ai-test/'+suffix,'title':'TEST ONLY','price':1000,'period':'month','currency':'GBP'})['home']
 def test_ai_auth_disabled_and_secret_not_persisted(self):
  h=self.home('disabled')
  with self.assertRaises(urllib.error.HTTPError):self.req('ai/config',{'api_key':FAKE_KEY,'enabled':True,'consent':True},False)
  with self.assertRaises(urllib.error.HTTPError):self.req('ai/enquiry',{'id':h['id'],'questions':['bills']})
  self.req('ai/config',{'api_key':FAKE_KEY,'enabled':True,'consent':True})
  self.assertNotIn(FAKE_KEY,json.dumps(self.req('bootstrap')));self.assertNotIn(FAKE_KEY,json.dumps(self.req('homes')));self.assertNotIn(FAKE_KEY.encode(),server.DB.read_bytes())
 def test_ai_reply_remains_pending_until_confirmation(self):
  self.enable();h=self.home('reply');text='Utilities are extra.'
  with patch.object(ai,'_transport',return_value=response({'summary_zh':'账单另付（模拟）','fields':[{'field':'bills','value':'excluded','evidence':text}]})):
   result=self.req('ai/reply',{'id':h['id'],'text':text})
  row=result['home'];self.assertEqual('',row['bills']);self.assertEqual('not_contacted',row['action_status']);self.assertEqual('openai',row['pending_reply']['engine'])
  confirmed=self.req('homes/'+h['id'],{'event':'confirm_reply','fields':{'bills':'excluded'}})
  self.assertEqual('excluded',confirmed['bills']);self.assertEqual(text,confirmed['field_sources']['bills']['evidence']);self.assertEqual('openai',confirmed['field_sources']['bills']['engine'])
 def test_concurrent_change_does_not_get_overwritten(self):
  self.enable();h=self.home('concurrent')
  def changed(payload,key):
   self.req('homes/'+h['id'],{'event':'edit','price':1100})
   return response({'summary_zh':'模拟','fields':[{'field':'bills','value':'excluded','evidence':'Bills excluded.'}]})
  with patch.object(ai,'_transport',side_effect=changed),self.assertRaises(urllib.error.HTTPError) as error:self.req('ai/reply',{'id':h['id'],'text':'Bills excluded.'})
  self.assertEqual(409,error.exception.code);row=next(x for x in self.req('homes') if x['id']==h['id']);self.assertEqual(1100,row['price']);self.assertNotIn('pending_reply',row)
 def test_brief_invalidation_and_minimal_connection_test(self):
  self.enable();h=self.home('brief')
  brief={'summary_zh':'模拟分析','questions':['请核实账单'],'next_steps':['联系房东确认'],'limitations':['未知费用未估计']}
  with patch.object(ai,'_transport',return_value=response(brief)):self.req('ai/brief',{'id':h['id']})
  row=next(x for x in self.req('homes') if x['id']==h['id']);self.assertFalse(row['ai_brief_stale']);self.assertEqual('not_contacted',row['action_status'])
  self.req('homes/'+h['id'],{'event':'edit','price':1100});self.assertTrue(next(x for x in self.req('homes') if x['id']==h['id'])['ai_brief_stale'])
  with patch.object(ai,'_transport',return_value=response({'message':'OK'})) as transport:self.req('ai/test',{})
  self.assertEqual({'text':'OK'},json.loads(transport.call_args.args[0]['input']));self.assertEqual('success',self.req('ai/status')['last_test'])
