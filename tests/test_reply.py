import importlib.util
from pathlib import Path
import unittest, test_flow, sys
spec=importlib.util.spec_from_file_location('server',Path(__file__).resolve().parents[1]/'apps/server/server.py')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/server'))
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
class ReplyFlow(unittest.TestCase):
 setUpClass=classmethod(test_flow.Flow.setUpClass.__func__)
 tearDownClass=classmethod(test_flow.Flow.tearDownClass.__func__)
 req=classmethod(test_flow.Flow.req.__func__)
 def test_reply_confirmation_is_separate(self):
  h=self.req('homes',{'project_id':'default','url':'https://example.org/reply-confirmation','title':'TEST ONLY'})['home'];path='homes/'+h['id']
  h=self.req(path,{'event':'draft','text':'Edited','questions':['bills','guarantor']})
  self.assertEqual('not_contacted',h['action_status']);self.assertIsNone(h['contacted_at'])
  text='Bills are not included. A UK guarantor is required. International students are welcome.'
  h=self.req(path,{'event':'extract_reply','text':text})
  self.assertEqual('',h['bills']);self.assertEqual('not_contacted',h['action_status'])
  self.assertEqual({'bills':'excluded','guarantor':'yes','students':'yes'},h['pending_reply']['fields'])
  import urllib.error
  for fields in ({},{'bills':'included'},{'price':250}):
   with self.assertRaises(urllib.error.HTTPError):self.req(path,{'event':'confirm_reply','fields':fields})
  h=self.req(path,{'event':'confirm_reply','fields':{'bills':'excluded','guarantor':'yes'}})
  self.assertEqual('excluded',h['bills']);self.assertEqual('yes',h['guarantor']);self.assertEqual('',h['students'])
  self.assertEqual('replied',h['action_status']);self.assertIsNone(h['contacted_at']);self.assertEqual(text,h['field_sources']['bills']['text']);self.assertIsNone(h['pending_reply'])
  h=self.req(path,{'event':'edit','url':h['url'],'title':h['title'],'bills':'excluded'})
  self.assertEqual('yes',h['guarantor'])
  row=next(x for x in self.req('homes') if x['id']==h['id']);self.assertNotIn('账单',row['assessment']['missing']);self.assertNotIn('英国担保人',row['assessment']['missing']);self.assertIn('接受留学生',row['assessment']['missing'])
  h=self.req(path,{'event':'extract_reply','text':'No UK guarantor is required.'});h=self.req(path,{'event':'reply_text'})
  self.assertEqual('yes',h['guarantor']);self.assertEqual('excluded',h['bills'])
 def test_conservative_extraction(self):
  cases=[('Bills included.',{'bills':'included'}),('No UK guarantor is required.',{'guarantor':'no'}),('不包含水电。不需要英国担保人。不接受国际学生。',{'bills':'excluded','guarantor':'no','students':'no'}),('Bills are included. Bills are not included.',{}),('Are bills included? A UK guarantor is required?',{}),('Maybe bills are included. If students are welcome, apply.',{}),('Not sure if bills are included.',{}),('Please call the office.',{})]
  for text,expected in cases:
   with self.subTest(text=text):self.assertEqual(expected,server.extract_reply(text))
