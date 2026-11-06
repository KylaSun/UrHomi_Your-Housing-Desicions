// Runs in an isolated extension world. Only reads public listing elements on demand.
// doc/url arguments make the same adapters testable against isolated HTML fixtures.
function urhomiPageContext(rawUrl){
 const u=new URL(rawUrl),host=u.hostname.toLowerCase();
 const site=['rightmove.co.uk','www.rightmove.co.uk'].includes(host)?'rightmove':['zoopla.co.uk','www.zoopla.co.uk'].includes(host)?'zoopla':'';
 const match=site==='rightmove'?u.pathname.match(/^\/properties\/(\d+)\/?$/):site==='zoopla'?u.pathname.match(/^\/to-rent\/details\/(\d+)\/?$/):null;
 return {site,id:match?.[1]||'',supported:!!match&&u.protocol==='https:',url:match?`https://www.${site}.co.uk/${site==='rightmove'?'properties/':'to-rent/details/'}${match[1]}${site==='zoopla'?'/':''}`:(u.hash='',u.href)};
}
function extractListing(doc=document,rawUrl=location.href){
 const ctx=urhomiPageContext(rawUrl);
 if(ctx.site&&!ctx.supported)throw Error('请打开单套出租房源详情页，搜索列表和出售房源不做租房分析。');
 const text=e=>(e?.innerText??e?.textContent??'').replace(/\u00a0/g,' ').trim();
 const visible=e=>e&&!e.closest('[hidden],[aria-hidden="true"],form,input,textarea,[data-urhomi-root]')&&(typeof e.getClientRects!=='function'||e.getClientRects().length>0);
 const first=selectors=>{for(const s of selectors){const e=[...doc.querySelectorAll(s)].find(visible);if(e)return e}return null};
 const titleEl=first(['main h1','h1[itemprop="streetAddress"]','h1']);
 const root=doc.querySelector('main')||doc.querySelector('#root')||doc.body;
 const title=text(titleEl).slice(0,250);
 // Detect explicit removed/challenge states without reading form values or private notes.
 const heading=text(first(['h1','h2']));
 const publicIntro=title&&!/^in the meantime|not found|page not found/i.test(title)?'':text(root).slice(0,1200);
 if(/just a moment|performing security verification|verify you are human|access denied|checking your browser|正在进行安全验证|请稍候|验证您不是/i.test(doc.title+' '+heading+' '+publicIntro+' '+text(first(['[role="alert"]']))))throw Error('网站正在进行安全验证，请在原网页完成后再读取；不会绕过验证。');
 if(/this property has been removed|listing (?:has been|is) removed|property is no longer available/i.test(doc.title+' '+publicIntro))throw Error('该房源已下架，无法读取当前租赁资料；原有保存和联系记录仍保留。');
 if(ctx.site==='rightmove'&&/\bfor sale\b/i.test(doc.title+' '+title))throw Error('这是出售房源，当前版本只分析出租房源。');
 if(ctx.site&&!title)throw Error('房源尚未加载完成，请稍后点击读取，或手动添加。');
 const sources={},warnings=[];
 const data={title:title||doc.title.slice(0,250),url:ctx.url,source:ctx.site==='rightmove'?'Rightmove':ctx.site==='zoopla'?'Zoopla':new URL(rawUrl).hostname,price:'',currency:'',period:'',room_type:'',bills:'',available_from:'',tenancy:'',guarantor:'',students:'',adapter:ctx.site||'generic',extracted_at:new Date().toISOString(),extraction_sources:sources,extraction_warnings:warnings};
 // Extract only the first current-listing price area. Never scan all body prices.
 const priceSelectors=ctx.site==='rightmove'?['[data-testid="property-price"]','[data-test="property-price"]','[data-testid="price"]','[class*="PropertyPrice_price"]']:ctx.site==='zoopla'?['[data-testid="listing-price"]','[data-testid="price"]','[data-testid="rental-price"]']:['[data-testid="property-price"]','[data-testid="listing-price"]'];
 let priceEl=first(priceSelectors),priceText=text(priceEl);
 if(!priceEl&&ctx.site==='rightmove'){
  priceEl=[...(root?.querySelectorAll('article')||[])].find(e=>visible(e)&&/£\s*[\d,]+(?:\.\d+)?\s*(?:pcm|pw)\b/i.test(text(e))&&text(e).length<650&&!e.querySelector('h2,h3'));
  priceText=text(priceEl);
 }
 if(!priceEl&&titleEl){
  // A bounded title header, excluding recommendation cards/agent contact sections.
  let parent=titleEl.parentElement;
  for(let i=0;parent&&i<3;i++,parent=parent.parentElement){
   const t=text(parent);if(t.length>1800||parent===root||parent.querySelector('form,textarea,[data-testid*="recommend"]'))break;
   if(/£\s*[\d,]+(?:\.\d+)?\s*(?:pcm|pw|per month|per week)\b/i.test(t)){priceEl=parent;priceText=t;break}
  }
 }
 const amounts=[...priceText.matchAll(/£\s*([\d,]+(?:\.\d{1,2})?)\s*(?:\/|per\s*)?(pcm|pw|month|week)\b/gi)].map(m=>({price:Number(m[1].replaceAll(',','')),period:/pcm|month/i.test(m[2])?'month':'week'}));
 const monthly=amounts.filter(x=>x.period==='month'),weekly=amounts.filter(x=>x.period==='week');
 const chosen=monthly.length?monthly:weekly;
 if(chosen.length&&new Set(chosen.map(x=>x.price)).size===1&&chosen[0].price>0){
  data.price=String(chosen[0].price);data.currency='GBP';data.period=chosen[0].period;sources.price={source:'当前房源主价格区域',text:priceText.slice(0,220)};
 }else warnings.push(chosen.length?'价格区域包含多项报价，请手动确认。':'未找到明确的当前房源租金及周期，请手动填写。');
 // Rightmove dt/dd pairs and semantic detail rows; never infer from site navigation.
 const details={};
 for(const dt of root?.querySelectorAll('dt')||[]){if(!visible(dt))continue;const dd=dt.nextElementSibling;if(dd?.tagName==='DD')details[text(dt).replace(/:$/,'').trim().toLowerCase()]=text(dd).slice(0,350)}
 const type=details['property type']||'';
 const descriptor=title+' '+type;
 data.room_type=/\bstudio\b/i.test(descriptor)?'studio':/\ben[ -]?suite\b/i.test(descriptor)?'ensuite':/\b(room|house share|flat share)\b/i.test(descriptor)?'shared':/\b(flat|apartment)\b/i.test(descriptor)?'apartment':'';
 const date=details['let available date']||details['available from']||'';
 // Only literal ISO dates are persisted; ambiguous UK dates and "now" stay unknown.
 if(/^\d{4}-\d{2}-\d{2}$/.test(date)&&!Number.isNaN(Date.parse(date)))data.available_from=date;
 if(date)sources.available_from={source:'页面租赁条件',text:date};
 if(details['minimum tenancy']){data.tenancy=details['minimum tenancy'];sources.tenancy={source:'页面租赁条件',text:data.tenancy}}
 let featureRoot=first(['[data-testid="key-features"]','[data-testid="listing-summary"]']);
 if(!featureRoot){const h=[...(root?.querySelectorAll('h2,h3')||[])].find(e=>visible(e)&&/^key features$|^property features$|^about this property$/i.test(text(e)));if(h){const candidate=h.closest('article,section')||h.parentElement;if(candidate!==root)featureRoot=candidate}}
 const featureNodes=[...(featureRoot?.querySelectorAll('li')||[])].filter(e=>visible(e)&&!e.closest('nav,aside,[role="navigation"]'));
 // Only short explicit statements; links to student search pages do not qualify.
 const statements=featureNodes.map(text).filter(t=>t.length<250&&!/[?？]/.test(t));
 const infer=(key,yes,no)=>{const positives=statements.filter(t=>yes.test(t)&&!no.test(t)),negatives=statements.filter(t=>no.test(t));if(positives.length&&!negatives.length){data[key]=key==='bills'?'included':'yes';sources[key]={source:'页面明确表述，待核实',text:positives[0]}}else if(negatives.length&&!positives.length){data[key]=key==='bills'?'excluded':'no';sources[key]={source:'页面明确表述，待核实',text:negatives[0]}}};
 infer('bills',/^(?:all |utility )?bills (?:are )?included(?: in (?:the )?rent)?[.!]?$/i,/^(?:all |utility )?bills (?:are )?(?:not included|excluded)[.!]?$/i);
 infer('students',/\b(?:international )?students (?:are )?(?:welcome|accepted)\b|^student friendly$/i,/\bno (?:international )?students\b|\bstudents (?:are )?not accepted\b/i);
 // Guarantor statements stay unknown here; asking the agent is safer than interpreting marketing copy.
 if(sources.available_from&&!data.available_from)warnings.push('可入住日期原文：'+date+'；尚未转换为确定日期。');
 if(ctx.site==='rightmove'&&!data.price&&/\bfor sale\b/i.test(doc.title))throw Error('这是出售房源，当前版本只分析出租房源。');
 // Only listing-scoped JSON-LD and explicit social image metadata; never stock imagery.
 const safeImage=value=>{if(typeof value!=='string'||!value.trim())return '';try{const u=new URL(value,rawUrl);return u.protocol==='https:'&&!u.username&&!u.password?u.href:''}catch{return ''}};
 let listing=null;
 function walk(value){if(!value||typeof value!=='object')return;if(Array.isArray(value)){value.forEach(walk);return}
 const types=[].concat(value['@type']||[]);
 if(types.some(t=>/^(Apartment|House|Residence|SingleFamilyResidence|Accommodation|RealEstateListing)$/.test(t))&&!listing)listing=value;
 if(value['@graph'])walk(value['@graph']);if(value.mainEntity)walk(value.mainEntity);if(value.about)walk(value.about);}
 for(const script of doc.querySelectorAll('script[type="application/ld+json"]')){try{walk(JSON.parse(script.textContent))}catch{}}
 const imageValue=value=>Array.isArray(value)?imageValue(value[0]):typeof value==='object'&&value?value.url||value.contentUrl: value;
 const meta=doc.querySelector('meta[property="og:image"]')||doc.querySelector('meta[name="twitter:image"]');
 data.image_url=safeImage(imageValue(listing?.image)||meta?.getAttribute('content')||'');
 const images=[];
 const addImage=(value,label)=>{const url=safeImage(value);if(url&&!images.some(x=>x.url===url)&&images.length<24)images.push({url,source:label})};
 const addStructured=value=>{if(Array.isArray(value))value.forEach(addStructured);else addImage(imageValue(value),'房源页 JSON-LD')};
 // Restrict DOM image discovery to the current listing gallery; never read recommendations or agent logos.
 addStructured(listing?.image);
 if(ctx.site==='rightmove')for(const meta of doc.querySelectorAll('a[itemprop="photo"] meta[itemprop="contentUrl"]'))addImage(meta.getAttribute('content'),'原房源相册元数据');
 const gallerySelectors=ctx.site==='rightmove'?[`a[href*="/properties/${ctx.id}"] img`,'[aria-label="Property image carousel"] img','[data-testid="property-gallery"] img']:['button[aria-label^="Property photo"] img','[aria-label="Gallery images"] img','[data-testid="gallery"] img'];
 for(const node of doc.querySelectorAll(gallerySelectors.join(','))){
  if(/floor.?plan|map|logo|agent|epc/i.test(node.getAttribute('alt')||''))continue;
  const srcsets=[node.getAttribute('srcset')||'',...[...(node.closest('picture')?.querySelectorAll('source[srcset]')||[])].map(x=>x.getAttribute('srcset')||'')].filter(Boolean).join(',');
  const variants=srcsets.split(',').map(x=>x.trim().split(/\s+/)).filter(x=>x[0]).map(x=>({url:x[0],size:parseFloat(x[1])||0})).sort((a,b)=>b.size-a.size);
  addImage(node.getAttribute('data-full-src')||node.getAttribute('data-original')||variants[0]?.url||node.currentSrc||node.getAttribute('src'),'原房源相册');
 }
 addStructured(listing?.image);
 addImage(data.image_url,'房源页图片元数据');
 data.images=images;data.image_url=images[0]?.url||'';
 data.image_source=data.image_url?(listing?.image?'房源页 JSON-LD':'房源页图片元数据'):'';
 data.image_page_url=ctx.url;
 const address=listing?.address;
 data.address=typeof address==='string'?address:address?[address.streetAddress,address.addressLocality,address.postalCode].filter(Boolean).join(', '):text(first(['[itemprop="streetAddress"]','[data-testid="address"]']));
 if(!data.address&&ctx.site==='zoopla'){const m=title.match(/\bto rent\s*(.+)$/i);if(m)data.address=m[1].trim()}
 const beds=details['bedrooms']||listing?.numberOfBedrooms;
 const bedMatch=String(beds??'').match(/^\s*(\d+)\s*(?:bedrooms?)?\s*$/i)||title.match(/\b(\d+)\s*bed(?:room)?s?\b/i);
 data.bedrooms=bedMatch?Number(bedMatch[1]):/\bstudio\b/i.test(title)?0:null;
 return data;
}
