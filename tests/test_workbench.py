import unittest, test_flow, urllib.error
class Workbench(unittest.TestCase):
 setUpClass=classmethod(test_flow.Flow.setUpClass.__func__)
 tearDownClass=classmethod(test_flow.Flow.tearDownClass.__func__)
 req=classmethod(test_flow.Flow.req.__func__)
 def row(self,h):return next(x for x in self.req('homes') if x['id']==h['id'])
 def test_cost_scope_unknown_zero_and_upfront(self):
  p=self.req('projects',{'name':'TEST cost scope','currency':'GBP','period':'month','budget':1000,'party_size':3})
  h=self.req('homes',{'project_id':p['id'],'url':'https://example.org/test/cost','price':2700,'period':'month','currency':'GBP'})['home']
  a=self.row(h)['assessment'];self.assertIsNone(a['cost']['rent_person']);self.assertIsNone(a['cost']['total_person']);self.assertEqual('unknown',a['fit'][0]['status'])
  h=self.req('homes/'+h['id'],{'event':'edit','rent_basis':'whole','bills':'excluded','bills_monthly':150,'transport_monthly':0,'deposit':3100,'prepaid_months':1,'tenancy_months':12})
  c=self.row(h)['assessment']['cost'];self.assertEqual(900,c['rent_person']);self.assertEqual(50,c['bills_person']);self.assertEqual(950,c['total_person']);self.assertEqual(5800,c['upfront']);self.assertEqual(11400,c['contract_person'])
 def test_confirmation_recalculates_cost_and_guarantor_fit(self):
  p=self.req('projects',{'name':'TEST fit','currency':'GBP','period':'month','budget':1300,'has_guarantor':'no'})
  h=self.req('homes',{'project_id':p['id'],'url':'https://example.org/test/confirmation-cost','price':1200,'currency':'GBP','period':'month','bills':'excluded','bills_monthly':200,'transport_monthly':0})['home'];path='homes/'+h['id']
  self.assertEqual(1400,self.row(h)['assessment']['cost']['total_person'])
  self.req(path,{'event':'extract_reply','text':'[TEST ONLY] Bills are included. A UK guarantor is required.'})
  self.assertEqual(1400,self.row(h)['assessment']['cost']['total_person'])
  self.req(path,{'event':'confirm_reply','fields':{'bills':'included','guarantor':'yes'}})
  a=self.row(h)['assessment'];self.assertEqual(1200,a['cost']['total_person']);self.assertEqual('conflict',next(r for r in a['fit'] if r['label']=='英国担保人')['status'])
 def test_demo_is_separate_and_reused_without_reset(self):
  default_before=[h['id'] for h in self.req('homes') if h['project_id']=='default'];result=self.req('demo',{});pid=result['project_id']
  project=next(p for p in self.req('bootstrap')['projects'] if p['id']==pid);self.assertTrue(project['is_demo'])
  homes=[h for h in self.req('homes') if h['project_id']==pid];self.assertEqual(2,len(homes));self.assertTrue(all(h['url'].startswith('https://example.org/urhomi-demo/') for h in homes));self.assertTrue(all(h['action_status']=='not_contacted' for h in homes))
  self.req('homes/'+homes[0]['id'],{'event':'decision','value':'shortlisted'});self.assertEqual(pid,self.req('demo',{})['project_id']);self.assertEqual('shortlisted',self.row(homes[0])['decision_status'])
  self.assertEqual(default_before,[h['id'] for h in self.req('homes') if h['project_id']=='default'])
 def test_extra_field_validation_and_progress(self):
  for value in (-1,0,1.5,21):
   with self.subTest(party=value),self.assertRaises(urllib.error.HTTPError):self.req('projects',{'name':'Invalid','party_size':value})
  for cost in (-1,'NaN','Infinity'):
   with self.subTest(cost=cost),self.assertRaises(urllib.error.HTTPError):self.req('homes',{'project_id':'default','url':'https://example.org/invalid','bills_monthly':cost})
  h=self.req('homes',{'project_id':'default','url':'https://example.org/test/progress'})['home'];path='homes/'+h['id']
  with self.assertRaises(urllib.error.HTTPError):self.req(path,{'event':'progress','value':'awaiting_reply'})
  h=self.req(path,{'event':'progress','value':'viewing_applying'});self.assertEqual('viewing_applying',h['action_status']);self.assertIsNone(h['contacted_at'])

 def test_listing_identity_deduplication(self):
  for base,variant in [('https://www.rightmove.co.uk/properties/987654321','https://rightmove.co.uk/properties/987654321/?utm_source=test#photos'),('https://www.zoopla.co.uk/to-rent/details/987654321/','https://zoopla.co.uk/to-rent/details/987654321?search_identifier=test')]:
   first=self.req('homes',{'project_id':'default','url':variant})['home']
   duplicate=self.req('homes',{'project_id':'default','url':base})
   self.assertTrue(duplicate['duplicate']);self.assertEqual(first['id'],duplicate['home']['id'])
   self.assertEqual(base,first['url']);self.assertIsNone(first['contacted_at'])

 def test_card_metadata_roundtrip_and_legacy_edit(self):
  h=self.req('homes',{'project_id':'default','url':'https://www.rightmove.co.uk/properties/555444','title':'TEST ONLY','address':'TEST Road','bedrooms':2,'image_url':'https://media.rightmove.co.uk/test.jpg','image_source':'房源页元数据','extracted_at':'2026-11-06T00:00:00Z'})['home']
  path='homes/'+h['id'];self.req(path,{'event':'decision','value':'shortlisted'})
  h=self.req(path,{'event':'edit','notes':'legacy form without photo fields'})
  self.assertEqual(2,h['bedrooms']);self.assertEqual('TEST Road',h['address']);self.assertEqual('https://media.rightmove.co.uk/test.jpg',h['image_url']);self.assertEqual('shortlisted',h['decision_status']);self.assertEqual('not_contacted',h['action_status'])
  h=self.req(path,{'event':'edit','image_url':'javascript:alert(1)'})
  self.assertEqual('',h['image_url'])

 def test_gallery_refresh_preserves_confirmed_fields(self):
  h=self.req('homes',{'project_id':'default','url':'https://example.org/gallery-test','price':500,'currency':'GBP','period':'week'})['home'];path='homes/'+h['id']
  self.req(path,{'event':'decision','value':'shortlisted'})
  h=self.req(path,{'event':'refresh_media','price':100,'images':[{'url':'https://images.example.org/a.jpg'},{'url':'https://images.example.org/b.jpg'},{'url':'javascript:alert(1)'}]})
  self.assertEqual(2,len(h['images']));self.assertEqual(500,h['price']);self.assertEqual('shortlisted',h['decision_status']);self.assertEqual('not_contacted',h['action_status'])
