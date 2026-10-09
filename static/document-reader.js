async function readWordDocument(view,bytes,content,status){
 status.textContent='Открываем документ для чтения…';content.setAttribute('aria-busy','true');
 try{
  const parsed=await new Promise((resolve,reject)=>{
   const worker=new Worker('/static/document-worker.js?v=15');let settled=false;
   const finish=(error,result)=>{if(settled)return;settled=true;clearTimeout(timer);worker.terminate();view.cancelDocument=null;error?reject(error):resolve(result);};
   const timer=setTimeout(()=>finish(Error('Документ не удалось открыть за 30 секунд. Закройте его и попробуйте ещё раз.')),30000);
   view.cancelDocument=()=>finish(new DOMException('Просмотр закрыт','AbortError'));
   worker.onmessage=event=>event.data.ok?finish(null,event.data):finish(Error(event.data.error));
   worker.onerror=()=>finish(Error('Не удалось запустить просмотр документа. Обновите страницу и попробуйте ещё раз.'));
   worker.postMessage({bytes},[bytes]);
  });
  if(view.disposed)return;
  const {default:purify}=await import('/static/vendor/documents/purify.es.mjs?v=3.4.16');if(view.disposed)return;
  const article=document.createElement('article');article.className='document-page';article.setAttribute('aria-label','Содержимое документа');
  // Uploaded documents may contain links, scripts or remote image URLs.
  // Keep readable content only; it cannot navigate or load remote resources.
  const fragment=purify.sanitize(parsed.html,{RETURN_DOM_FRAGMENT:true,ALLOWED_TAGS:['p','br','div','span','strong','b','em','i','u','s','sup','sub','h1','h2','h3','h4','h5','h6','ul','ol','li','table','thead','tbody','tfoot','tr','td','th','pre','blockquote','hr','img','a'],ALLOWED_ATTR:['style','colspan','rowspan','alt','src','start','type'],ALLOW_DATA_ATTR:false,ALLOW_ARIA_ATTR:false});
  for(const element of fragment.querySelectorAll('*')){
   const style=element.style,kept=[];
   for(const [property,pattern] of [['font-weight',/^(normal|bold|[1-9]00)$/],['font-style',/^(normal|italic|oblique)$/],['text-decoration',/^(underline|line-through|underline line-through)$/],['text-align',/^(left|right|center|justify)$/],['vertical-align',/^(super|sub|baseline)$/]]){
    const value=style?.getPropertyValue(property).trim();if(value&&pattern.test(value))kept.push(property+':'+value);
   }
   element.removeAttribute('style');if(kept.length)element.setAttribute('style',kept.join(';'));
   if(element.tagName==='IMG'&&!/^data:image\/(?:png|jpeg|gif|webp);base64,[a-z0-9+/=\s]+$/i.test(element.getAttribute('src')||''))element.remove();
   if(element.tagName==='A')element.replaceWith(...element.childNodes);
  }
  article.append(fragment);content.replaceChildren(article);
  paginateDocument(view,article,status);
 }finally{content.removeAttribute('aria-busy');}
}
