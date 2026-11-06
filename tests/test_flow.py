import unittest, tempfile, subprocess, os, sys, json, urllib.request, urllib.error, socket, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class Flow(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close()
  cls.base=f'http://127.0.0.1:{cls.port}'
  cls.proc=subprocess.Popen([sys.executable,str(ROOT/'apps/server/server.py'),'--port',str(cls.port)],env={**os.environ,'URHOMI_DB':cls.tmp.name+'/test.sqlite3'},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  for _ in range(80):
   try:cls.token=cls.req('bootstrap')['token'];break
   except Exception:time.sleep(.05)
  else:raise RuntimeError(cls.proc.stderr.read().decode())
 @classmethod
 def tearDownClass(cls):
  cls.proc.terminate();cls.proc.wait();cls.proc.stdout.close();cls.proc.stderr.close();cls.tmp.cleanup()
 @classmethod
 def req(cls,path,data=None,token=True):
  headers={'Content-Type':'application/json'}
  if token and hasattr(cls,'token'):headers['Authorization']='Bearer '+cls.token
  req=urllib.request.Request(cls.base+'/api/'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
  with urllib.request.urlopen(req) as r:return json.load(r)
 def test_full_capture_contact_reply_persistence(self):
  p=self.req('projects',{'name':'Test','budget':300,'period':'week','currency':'GBP','room_type':'studio'})
  data={'project_id':p['id'],'title':'TEST ONLY','url':'https://example.org/home/1#tracking','price':250,'currency':'GBP','period':'week','room_type':'studio'}
  r=self.req('homes',data);h=r['home'];ident=h['id'];self.assertFalse(r['duplicate'])
  self.assertTrue(self.req('homes',data)['duplicate'])
  captured=next(x for x in self.req('homes') if x['id']==ident)
  self.assertIn('账单',captured['assessment']['missing']);self.assertEqual([],captured['assessment']['conflicts'])
  self.assertEqual('https://example.org/home/1',h['url'])
  path='homes/'+ident
  h=self.req(path,{'event':'prepare'});self.assertIn('bills',h['draft']);self.assertEqual('not_contacted',h['action_status'])
  h=self.req(path,{'event':'draft','text':'Edited enquiry'});self.assertIsNone(h['contacted_at'])
  h=self.req(path,{'event':'decision','value':'shortlisted'});self.assertEqual('not_contacted',h['action_status'])
  h=self.req(path,{'event':'contact','text':'Edited enquiry','days':2});self.assertEqual('awaiting_reply',h['action_status']);self.assertTrue(h['follow_up_at']);self.assertEqual('shortlisted',h['decision_status'])
  h=self.req(path,{'event':'reply','text':'TEST reply: viewing offered','action':'viewing_applying'});self.assertIsNone(h['follow_up_at']);self.assertTrue(h['last_response_at']);self.assertEqual('',h['bills'])
  self.assertEqual('TEST reply: viewing offered',h['history'][-1]['text'])
  self.proc.terminate();self.proc.wait();self.proc.stdout.close();self.proc.stderr.close()
  type(self).proc=subprocess.Popen([sys.executable,str(ROOT/'apps/server/server.py'),'--port',str(self.port)],env={**os.environ,'URHOMI_DB':self.tmp.name+'/test.sqlite3'},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  for _ in range(80):
   try:self.req('bootstrap');break
   except Exception:time.sleep(.05)
  self.assertEqual(h['history'],next(x for x in self.req('homes') if x['id']==ident)['history'])
  self.req(path,{'event':'delete'})
 def test_validation_and_security(self):
  for url in ['javascript:alert(1)','file:///etc/passwd','https://user:password@example.org']:
   with self.assertRaises(urllib.error.HTTPError) as e:self.req('homes',{'project_id':'default','url':url})
   self.assertEqual(400,e.exception.code)
  with self.assertRaises(urllib.error.HTTPError) as e:self.req('projects',{'name':'Unauthorized'},False)
  self.assertEqual(403,e.exception.code)
  req=urllib.request.Request(self.base+'/api/bootstrap',headers={'Host':'evil.example'})
  with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
  self.assertEqual(403,e.exception.code)
  with self.assertRaises(urllib.error.HTTPError):self.req('homes',{'project_id':'default','url':'https://example.org','price':'NaN'})
 def test_budget_and_project_isolation(self):
  p=self.req('projects',{'name':'Monthly','budget':1000,'currency':'GBP','period':'month'})
  h=self.req('homes',{'project_id':p['id'],'url':'https://example.org/expensive','price':300,'currency':'GBP','period':'week'})['home']
  row=next(x for x in self.req('homes') if x['id']==h['id']);self.assertTrue(row['assessment']['conflicts'])
  other=self.req('homes',{'project_id':'default','url':h['url']})
  self.assertFalse(other['duplicate']);self.assertNotEqual(other['home']['id'],h['id'])
if __name__=='__main__':unittest.main()
