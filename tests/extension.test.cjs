// Run with Node.js: node tests/extension.test.cjs
// Chrome APIs are mocked; this does not replace an unpacked Chrome install test.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=path.join(__dirname,'../apps/extension');
const code=name=>fs.readFileSync(path.join(dir,name),'utf8');
module.exports=(async()=>{
 let handler,order=[],response,request;
 const bg=vm.createContext({URL,console,chrome:{sidePanel:{setPanelBehavior:()=>Promise.resolve(),open:options=>{order.push('open');assert.equal(options.windowId,7);return Promise.resolve()}},storage:{session:{set:async data=>{order.push('store');request=data}}},runtime:{onMessage:{addListener:f=>handler=f}}}});
 bg.importScripts=()=>vm.runInContext(code('extract.js'),bg);vm.runInContext(code('background.js'),bg);
 assert.equal(handler({type:'URHOMI_OPEN'},{url:'https://www.rightmove.co.uk/properties/123?foo=bar',tab:{id:42,windowId:7}},r=>response=r),true);
 await new Promise(setImmediate);
 assert.deepEqual(order,['open','store']);assert.equal(response.ok,true);assert.equal(request['urhomiOpen:7'].url,'https://www.rightmove.co.uk/properties/123');assert.equal(request['urhomiOpen:7'].tabId,42);
 console.log('PASS: page click opens synchronously before storage; canonical request survives panel startup');
 order=[];handler({type:'URHOMI_OPEN'},{url:'https://www.rightmove.co.uk.evil.test/properties/123',tab:{id:42,windowId:7}},r=>response=r);assert.equal(response.ok,false);assert.equal(order.length,0);
 handler({type:'URHOMI_OPEN'},{url:'https://www.zoopla.co.uk/to-rent/property/london/',tab:{id:42,windowId:7}},r=>response=r);assert.equal(response.ok,false);
 console.log('PASS: unsupported origins and search pages cannot request a panel open');
 let timer,hosts=[],sends=0;const location={href:'https://www.rightmove.co.uk/properties/123'};
 const doc={body:{append:h=>{h.isConnected=true;hosts.push(h)}},createElement:()=>{const buttons={'#hint':{textContent:''},'#open':{},'#hide':{}};return{dataset:{},style:{},isConnected:false,attachShadow(){this.shadow={querySelector:k=>buttons[k]};return this.shadow},remove(){this.isConnected=false}}}};
 const cs=vm.createContext({URL,location,document:doc,setInterval:f=>timer=f,window:{addEventListener(){}},chrome:{runtime:{sendMessage:async data=>{sends++;assert.equal(data.type,'URHOMI_OPEN');return{ok:true}}}}});
 vm.runInContext(code('extract.js'),cs);vm.runInContext(code('content.js'),cs);assert.equal(sends,0);assert.equal(hosts.length,1);
 vm.runInContext(code('content.js'),cs);assert.equal(hosts.length,1);timer();assert.equal(hosts.length,1);
 hosts[0].shadow.querySelector('#open').onclick();await new Promise(setImmediate);assert.equal(sends,1);assert.match(hosts[0].shadow.querySelector('#hint').textContent,/已打开/);
 console.log('PASS: one isolated launcher; no read or message before click; repeated injection does not duplicate it');
 hosts[0].shadow.querySelector('#hide').onclick();timer();assert.equal(hosts.length,1);assert.equal(hosts[0].isConnected,false);
 location.href='https://www.rightmove.co.uk/properties/456';timer();assert.equal(hosts.length,2);assert.equal(hosts[1].isConnected,true);
 location.href='https://www.rightmove.co.uk/property-to-rent/london.html';timer();assert.equal(hosts[1].isConnected,false);
 console.log('PASS: hide applies to this listing; SPA navigation remounts only on detail pages');
})();
