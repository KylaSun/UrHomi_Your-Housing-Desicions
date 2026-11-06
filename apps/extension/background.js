importScripts('extract.js');
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(console.error);
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
 if(message?.type!=='URHOMI_OPEN')return;
 if(!sender.tab||!urhomiPageContext(sender.url||sender.tab.url||'about:blank').supported){respond({ok:false,error:'请在 Rightmove 或 Zoopla 的出租详情页使用。'});return}
 // Call open immediately inside the click-message handler to retain the user gesture.
 const opening=chrome.sidePanel.open({windowId:sender.tab.windowId});
 const request={tabId:sender.tab.id,windowId:sender.tab.windowId,url:urhomiPageContext(sender.url||sender.tab.url).url,at:Date.now(),save:message.save===true};
 const pending=chrome.storage.session.set({['urhomiOpen:'+sender.tab.windowId]:request});
 Promise.all([opening,pending]).then(()=>respond({ok:true})).catch(()=>respond({ok:false,error:'未能打开侧栏，请点击工具栏中的 UrHomi 图标重试。'}));
 return true;
});
