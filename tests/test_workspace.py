from test_flow import Flow
import urllib.error
class Workspace(Flow):
 def test_private_workspace_validation_isolation_and_persistence(self):
  a=self.req('projects',{'name':'Workspace A'})['id']
  b=self.req('projects',{'name':'Workspace B'})['id']
  fields={'display_name':'Test student','area':'London · Bloomsbury','area_notes':'Check route','roommates_draft':'Quiet evenings','bio':'Student','lifestyle':'Early sleeper'}
  self.assertEqual(fields,self.req('workspace',{'project_id':a,'fields':fields}))
  self.req('workspace',{'project_id':b,'fields':{'display_name':'Another'}})
  self.assertEqual(fields,self.req('bootstrap')['workspace'][a])
  self.req('workspace',{'project_id':a,'fields':{'campus_draft':'Question'}})
  self.assertEqual('Quiet evenings',self.req('bootstrap')['workspace'][a]['roommates_draft'])
  for data in [{'project_id':'missing','fields':{}},{'project_id':a,'fields':{'exact_location':'x'}},{'project_id':a,'fields':{'bio':'x'*1001}}]:
   with self.assertRaises(urllib.error.HTTPError) as error:self.req('workspace',data)
   self.assertEqual(400,error.exception.code)
  with self.assertRaises(urllib.error.HTTPError) as error:self.req('workspace',{'project_id':a,'fields':{'bio':'bad'}},token=False)
  self.assertEqual(403,error.exception.code)
  self.assertEqual('Student',self.req('bootstrap')['workspace'][a]['bio'])
