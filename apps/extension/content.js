// No extraction, network, forms or messages are read before a user clicks.
(()=>{
 if(globalThis.__urhomiLauncher)return;globalThis.__urhomiLauncher=true;
 let host=null,lastUrl='',dismissed=new Set();
 function update(){
  const ctx=urhomiPageContext(location.href);
  if(location.href===lastUrl&&host?.isConnected)return;
  lastUrl=location.href;
  if(!ctx.supported||dismissed.has(ctx.url)){host?.remove();host=null;return}
  if(host?.isConnected)return;
  host=document.createElement('div');host.dataset.urhomiRoot='true';
  host.style.cssText='position:fixed;right:20px;bottom:24px;z-index:2147483000;';
  const shadow=host.attachShadow({mode:'open'});
  shadow.innerHTML=`<style>:host{all:initial;font-family:system-ui,sans-serif}.wrap{background:#fff;border:1px solid #d9e3d5;border-radius:16px;padding:8px;box-shadow:0 7px 28px #19382e30;max-width:280px}button{font:14px/1.4 system-ui,sans-serif;cursor:pointer;border:0;border-radius:10px;padding:12px;color:white;background:#245a48}.close{background:white;color:#66786d;padding:8px}button:focus-visible{outline:3px solid #cba34e;outline-offset:2px}p{font:12px/1.5 system-ui,sans-serif;color:#64766a;margin:6px 8px;max-width:240px}</style><div class="wrap"><button id="open" aria-label="保存这套房源到 UrHomi">保存到我的房源</button><button id="hide" class="close" aria-label="隐藏当前房源的 UrHomi 入口">×</button><p id="hint" role="status">自动读取当前房源，保存后可在 UrHomi 查看</p></div>`;
  shadow.querySelector('#open').onclick=()=>{
   const hint=shadow.querySelector('#hint');hint.textContent='正在打开右侧看房助手…';
   chrome.runtime.sendMessage({type:'URHOMI_OPEN',save:true}).then(r=>{hint.textContent=r?.ok?'已打开侧栏，请核实提取结果。':r?.error||'请点击浏览器工具栏中的 UrHomi 图标。'}).catch(()=>{hint.textContent='插件已更新，请刷新房源页后重试。'});
  };
  shadow.querySelector('#hide').onclick=()=>{dismissed.add(urhomiPageContext(location.href).url);host.remove();host=null};
  document.body.append(host);
 }
 update();
 // Covers client-side navigation and browser back/forward without patching site code.
 setInterval(update,1000);window.addEventListener('popstate',update);
})();
