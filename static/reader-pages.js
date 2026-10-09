function readerNavigation(view,total,onSelect,label='Страница'){
 const form=node('form','reader-navigation'),prev=button('←',()=>choose(current-1)),next=button('→',()=>choose(current+1));
 prev.setAttribute('aria-label','Предыдущая страница');next.setAttribute('aria-label','Следующая страница');
 const field=node('label','reader-page-label'),input=node('input','reader-page-number'),count=node('span','reader-page-total'),submit=node('button','fd-secondary','Перейти'),error=node('span','reader-page-error');form.noValidate=true;
 input.type='text';input.inputMode='numeric';input.pattern='[0-9]+';input.required=true;input.autocomplete='off';input.setAttribute('aria-label','Номер страницы');submit.type='submit';error.setAttribute('role','status');
 field.append(input,count);form.append(prev,field,submit,next,error);view.host.insertBefore(form,view.scroller);let current=1,busy=false;
 function set(pages,value,loading=false){total=Math.max(1,pages);current=value;busy=loading;input.value=String(value);input.setAttribute('aria-description','От 1 до '+total);count.textContent='из '+total;prev.disabled=loading||value<=1;next.disabled=loading||value>=total;input.disabled=loading;submit.disabled=loading;if(view.reader){view.reader.current=value;view.reader.total=total;view.reader.busy=loading;}}
 async function choose(value){
  if(view.disposed||busy||view.turning)return;
  if(!Number.isSafeInteger(value)||value<1||value>total){error.textContent='Введите страницу от 1 до '+total;return;}
  error.textContent='';const previous=current;if(value===previous)return;
  view.turning=true;let sheet;
  try{sheet=readerTurnSnapshot(view,value-previous);await onSelect(value);if(!view.disposed&&current!==previous)await animateReaderTurn(view,sheet);}
  catch(e){if(!view.disposed)error.textContent=e.message||'Не удалось открыть страницу';}
  finally{sheet?.remove();view.turning=false;}
 }
 form.onsubmit=event=>{event.preventDefault();choose(/^\d+$/.test(input.value.trim())?Number(input.value):NaN);};
 set(total,1);return {set,choose,element:form};
}
function paginateDocument(view,article,status){
 const flow=node('div','document-flow'),viewport=node('div','document-viewport');flow.append(...article.childNodes);viewport.append(flow);article.append(viewport);article.classList.add('document-paginated');
 view.scroller.classList.add('paged-scroller');article.parentElement.classList.add('paged-content');
 let current=1,total=1,step=1,frame=0;
 const pager=readerNavigation(view,1,number=>{current=number;viewport.scrollLeft=(number-1)*step;pager.set(total,current);},'Страница');
 view.reader={mode:'word',current:1,total:1,busy:false,choose:pager.choose,anchor:()=>wordPageAnchor(flow,viewport),openBookmark:bookmark=>{
  const offset=Math.max(0,Number(bookmark.offset)||0),walker=document.createTreeWalker(flow,NodeFilter.SHOW_TEXT);let used=0,text;
  while((text=walker.nextNode())){if(used+text.length>offset){const range=document.createRange(),at=offset-used;range.setStart(text,at);range.setEnd(text,Math.min(text.length,at+1));const box=range.getBoundingClientRect();return pager.choose(Math.min(total,Math.max(1,Math.floor((box.left-viewport.getBoundingClientRect().left+viewport.scrollLeft)/step)+1)));}used+=text.length;}
  return pager.choose(Math.min(total,bookmark.page||1));
 }};
 status.textContent='Страницы режима чтения · нумерация зависит от размера экрана';
 function layout(){
  if(view.disposed)return;const width=viewport.clientWidth;if(!width)return;
  const ratio=(current-1)/total;step=width+32;flow.style.columnWidth=width+'px';flow.style.columnGap='32px';
  total=Math.max(1,Math.ceil((flow.scrollWidth+32)/step-0.01));current=Math.min(total,Math.floor(ratio*total)+1);viewport.scrollLeft=(current-1)*step;pager.set(total,current);
 }
 const observer=new ResizeObserver(()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(layout);});observer.observe(viewport);
 view.cleanups.push(()=>{observer.disconnect();cancelAnimationFrame(frame);});
 for(const img of flow.querySelectorAll('img'))img.addEventListener('load',layout,{once:true});
 let textSize=16;
 try{const saved=Number(localStorage.getItem('fgu-reader-text-size'));if(saved>=10&&saved<=40)textSize=saved;}catch{}
 article.style.setProperty('--reader-text-size',textSize+'px');
 layout();
 readerScale(view,{label:'Размер текста',min:10,max:40,step:2,value:textSize,format:value=>value+' px',apply:async value=>{
  const anchor=wordPageAnchor(flow,viewport);article.style.setProperty('--reader-text-size',value+'px');await new Promise(requestAnimationFrame);layout();await view.reader.openBookmark(anchor);
  try{localStorage.setItem('fgu-reader-text-size',String(value));}catch{}
 }});
 readerBookmarks(view);
}
function wordPageAnchor(flow,viewport){
 const bounds=viewport.getBoundingClientRect(),walker=document.createTreeWalker(flow,NodeFilter.SHOW_TEXT);let used=0,text;
 while((text=walker.nextNode())){
  const range=document.createRange();range.selectNodeContents(text);const visible=[...range.getClientRects()].some(rect=>rect.right>bounds.left+1&&rect.left<bounds.right-1&&rect.bottom>bounds.top&&rect.top<bounds.bottom);
  if(visible&&text.length){let low=0,high=text.length-1;while(low<high){const mid=Math.floor((low+high)/2);range.setStart(text,mid);range.setEnd(text,mid+1);if(range.getBoundingClientRect().right<=bounds.left+1)low=mid+1;else high=mid;}return {offset:used+low,excerpt:flow.textContent.slice(used+low,used+low+70).trim()};}
  used+=text.length;
 }return {offset:0,excerpt:''};
}
async function readerBookmarks(view){
 const prefix='reader-bookmark:'+view.file.id+':',section=node('details','reader-bookmarks'),summary=node('summary'),list=node('div','reader-bookmark-list'),message=node('p','reader-bookmark-message');message.setAttribute('role','status');
 const add=button('☆ Добавить закладку',async()=>{
  const reader=view.reader;if(!reader||reader.busy)return;add.disabled=true;
  try{
   const anchor=reader.anchor?.()||{},bookmark={type:'file-bookmark',file:String(view.file.id),mode:reader.mode,page:reader.current,...anchor,title:'Закладка: '+view.file.title,text:'Страница '+reader.current};
   const item=prefix+readerUuid();await saveReaderBookmark({kind:'note',item,body:JSON.stringify(bookmark)});
   if(view.disposed)return;records.push({item,...bookmark});draw();message.textContent='Закладка сохранена';readerNotice(view,message.textContent);
  }catch(error){if(!view.disposed){message.textContent='Не удалось сохранить закладку: '+error.message;view.status.textContent=message.textContent;readerNotice(view,message.textContent);}}
  finally{add.disabled=false;}
 },'fd-secondary');
 section.append(summary,list,message);view.actions.append(add,section);let records=[];
 function draw(){
  summary.textContent='Закладки ('+records.length+')';list.replaceChildren();if(!records.length)list.append(node('p','muted','Здесь появятся ваши закладки в этом файле.'));
  for(const bookmark of [...records].sort((a,b)=>a.page-b.page)){
   const row=node('div','reader-bookmark-row'),open=button('Страница '+bookmark.page+(bookmark.excerpt?' · '+bookmark.excerpt:''),async()=>{
    if(view.reader.busy)return;section.open=false;if(view.reader.openBookmark)await view.reader.openBookmark(bookmark);else await view.reader.choose(Math.min(view.reader.total,bookmark.page));
   },'fd-secondary');
   const remove=button('×',async()=>{remove.disabled=true;try{await saveReaderBookmark({kind:'note',item:bookmark.item,delete:true});if(view.disposed)return;records=records.filter(record=>record.item!==bookmark.item);draw();message.textContent='Закладка удалена';readerNotice(view,message.textContent);}catch(error){message.textContent=error.message;view.status.textContent='Не удалось удалить закладку: '+error.message;readerNotice(view,view.status.textContent);}finally{remove.disabled=false;}},'fd-secondary');remove.setAttribute('aria-label','Удалить закладку на страницу '+bookmark.page);row.append(open,remove);list.append(row);
  }
 }
 draw();add.disabled=true;
 try{const saved=await api('personal');if(view.disposed)return;records=saved.filter(row=>row.kind==='note'&&row.item.startsWith(prefix)).flatMap(row=>{try{const data=JSON.parse(row.body);return data.type==='file-bookmark'&&data.file===String(view.file.id)&&Number.isSafeInteger(data.page)&&data.page>0?[{...data,item:row.item}]:[];}catch{return [];}});draw();}
 catch(error){if(!view.disposed){message.textContent='Не удалось загрузить закладки: '+error.message;view.status.textContent=message.textContent;readerNotice(view,message.textContent);}}
 finally{add.disabled=false;}
}
function readerFullscreen(view){
 const telegram=!!(tg?.initData&&tg?.isVersionAtLeast?.('8.0')&&tg?.requestFullscreen);
 const standalone=()=>navigator.standalone===true||matchMedia('(display-mode: standalone)').matches||matchMedia('(display-mode: fullscreen)').matches;
 const nativeFull=()=>document.fullscreenElement===view.host||document.webkitFullscreenElement===view.host||(telegram&&tg.isFullscreen);
 const alreadyTelegramFull=telegram&&tg.isFullscreen;let requested=false,pending=false,timer=0;
 const control=node('button','fd-secondary reader-fullscreen','⛶');control.type='button';
 const message=node('div','reader-fullscreen-message'),text=node('p'),dismiss=button('Понятно',()=>{message.hidden=true;},'fd-secondary');
 message.hidden=true;message.setAttribute('role','status');message.append(text,dismiss);view.host.append(message);
 function showReason(){
  if(view.disposed)return;
  const apple=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  text.textContent=apple&&!telegram?'Этот браузер не разрешил развернуть книгу на весь экран телефона. Откройте сайт в Safari → «Поделиться» → «На экран Домой», включите «Открывать как веб-приложение», если этот переключатель есть. Затем запускайте дневник с новой иконки — без панелей браузера. Системная строка телефона может остаться.':telegram?'Telegram не подтвердил полный экран. Обновите Telegram и повторите нажатие ⛶.':'Браузер не разрешил полный экран. Повторите нажатие ⛶. Если режим недоступен, откройте дневник в Chrome или добавьте его на главный экран через меню браузера.';
  message.hidden=false;
 }
 function change(){
  clearTimeout(timer);pending=false;
  const full=nativeFull()||standalone();view.host.dataset.nativeFullscreen=String(!!nativeFull());
  control.setAttribute('aria-label',nativeFull()?'Выйти из полного экрана':standalone()?'Режим чтения без панелей':'Во весь экран телефона');control.title=control.getAttribute('aria-label');
  if(full)message.hidden=true;
 }
 function failed(){change();if(!nativeFull()&&!standalone())showReason();}
 async function enter(manual=false){
  if(view.disposed)return;view.setReadingMode?.(true);
  if(nativeFull()){change();return;}
  if(standalone()&&!view.host.requestFullscreen&&!view.host.webkitRequestFullscreen){change();return;}
  if(pending&&!manual)return;clearTimeout(timer);pending=true;message.hidden=true;
  try{
   if(telegram){requested=true;tg.requestFullscreen();timer=setTimeout(()=>{if(!view.disposed&&!tg.isFullscreen)failed();},2500);return;}
   const request=view.host.requestFullscreen||view.host.webkitRequestFullscreen;
   if(!request){failed();return;}
   // Called synchronously from the file/fullscreen click, preserving user activation.
   const promise=view.host.requestFullscreen?request.call(view.host,{navigationUI:'hide'}):request.call(view.host);await promise;
   if(view.disposed){if(document.fullscreenElement===view.host)await document.exitFullscreen();return;}
   change();
  }catch{failed();}finally{if(!telegram)pending=false;}
 }
 async function toggle(){
  if(nativeFull()){
   try{if(telegram&&tg.isFullscreen)tg.exitFullscreen();else await (document.exitFullscreen||document.webkitExitFullscreen).call(document);}catch{failed();}
   view.setReadingMode?.(false);
  }else if(standalone()&&!view.host.requestFullscreen&&!view.host.webkitRequestFullscreen){view.setReadingMode?.(!view.host.classList.contains('reader-immersive'));}
  else await enter(true);
 }
 control.onclick=()=>{void toggle();};view.enterFullscreen=()=>enter(false);change();
 document.addEventListener('fullscreenchange',change);document.addEventListener('webkitfullscreenchange',change);
 if(telegram){tg.onEvent?.('fullscreenChanged',change);tg.onEvent?.('fullscreenFailed',failed);}
 view.cleanups.push(()=>{
  clearTimeout(timer);document.removeEventListener('fullscreenchange',change);document.removeEventListener('webkitfullscreenchange',change);
  if(telegram){tg.offEvent?.('fullscreenChanged',change);tg.offEvent?.('fullscreenFailed',failed);if(requested&&!alreadyTelegramFull){try{tg.exitFullscreen();}catch{}}}
  if(document.fullscreenElement===view.host||document.webkitFullscreenElement===view.host){try{Promise.resolve((document.exitFullscreen||document.webkitExitFullscreen).call(document)).catch(()=>{});}catch{}}
 });return control;
}

function readerPhoneMode(view){
 const tools=button('☰ Меню',()=>setTools(!view.host.classList.contains('reader-tools-open')),'fd-secondary reader-tools-toggle');tools.setAttribute('aria-label','Показать меню чтения');tools.setAttribute('aria-expanded','false');
 const close=button('×',closeFile,'fd-secondary reader-floating-close');close.setAttribute('aria-label','Закрыть книгу');
 const download=view.actions.querySelector('.reader-download').cloneNode(true);download.className='fd-secondary reader-floating-download';download.textContent='↓ Скачать';download.setAttribute('aria-label','Скачать файл в загрузки');download.onclick=event=>readerDownload(view,event);view.host.append(tools,download,close);
 function setTools(open){view.host.classList.toggle('reader-tools-open',open);tools.setAttribute('aria-expanded',String(open));tools.setAttribute('aria-label',open?'Скрыть меню чтения':'Показать меню чтения');}
 view.setReadingMode=enabled=>{view.host.classList.toggle('reader-immersive',enabled);setTools(!enabled);};
 const panels=[view.host.querySelector('.file-toolbar'),view.actions];
 const observer=new ResizeObserver(()=>{
  const toolbar=view.host.querySelector('.file-toolbar');view.host.style.setProperty('--reader-toolbar-height',toolbar.offsetHeight+'px');view.host.style.setProperty('--reader-actions-height',view.actions.offsetHeight+'px');
 });panels.forEach(panel=>observer.observe(panel));
 view.cleanups.push(()=>observer.disconnect());
 view.setReadingMode(false);
}

function readerTurnSnapshot(view,direction){
 if(matchMedia('(prefers-reduced-motion: reduce)').matches)return null;
 const source=view.scroller.querySelector('.document-viewport,.pdf-canvas,.pdf-reading-page');if(!source)return null;
 const rect=source.getBoundingClientRect(),hostRect=view.host.getBoundingClientRect();
 const sheet=node('div','reader-turn-sheet'),copy=source.cloneNode(true);sheet.setAttribute('aria-hidden','true');sheet.inert=true;
 Object.assign(sheet.style,{left:(rect.left-hostRect.left)+'px',top:(rect.top-hostRect.top)+'px',width:rect.width+'px',height:rect.height+'px'});
 copy.style.width=rect.width+'px';copy.style.height=rect.height+'px';sheet.append(copy);view.host.append(sheet);copy.scrollLeft=source.scrollLeft;
 const originals=source.querySelectorAll('canvas');copy.querySelectorAll('canvas').forEach((canvas,i)=>canvas.getContext('2d').drawImage(originals[i],0,0));
 sheet.dataset.direction=direction>0?'next':'previous';
 return sheet;
}
async function animateReaderTurn(view,sheet){
 if(!sheet)return;
 const forward=sheet.dataset.direction==='next';sheet.style.transformOrigin=forward?'left center':'right center';
 const animation=sheet.animate([
  {transform:'perspective(1600px) rotateY(0deg)',opacity:1,filter:'brightness(1)'},
  {transform:'perspective(1600px) rotateY('+(forward?-55:55)+'deg)',opacity:.85,filter:'brightness(.8)',offset:.55},
  {transform:'perspective(1600px) rotateY('+(forward?-105:105)+'deg)',opacity:0,filter:'brightness(.6)'}
 ],{duration:380,easing:'cubic-bezier(.25,.7,.25,1)',fill:'forwards'});
 view.turnAnimation=animation;try{await animation.finished;}catch{}finally{sheet.remove();view.turnAnimation=null;}
}
function readerSwipes(view){
 let gesture=null;const surface=view.scroller;surface.classList.add('reader-swipe-surface');
 const ignore=target=>target.closest('a,button,input,select,textarea,summary,audio,video,[contenteditable="true"]');
 function start(e){if(!e.isPrimary||e.button>0||ignore(e.target)||view.reader?.busy||view.turning||String(getSelection())){gesture=null;return;}gesture={id:e.pointerId,x:e.clientX,y:e.clientY,at:performance.now()};}
 function end(e){const g=gesture;gesture=null;if(!g||g.id!==e.pointerId||String(getSelection()))return;const dx=e.clientX-g.x,dy=e.clientY-g.y;
  if(Math.abs(dx)<50||Math.abs(dx)<Math.abs(dy)*1.5||performance.now()-g.at>1200)return;
  const reader=view.reader;if(!reader||reader.busy||view.turning||view.pdfZoom>1)return;const next=reader.current+(dx<0?1:-1);if(next>=1&&next<=reader.total)void reader.choose(next);
 }
 function cancel(){gesture=null;}
 surface.addEventListener('pointerdown',start);surface.addEventListener('pointerup',end);surface.addEventListener('pointercancel',cancel);
 view.cleanups.push(()=>{surface.removeEventListener('pointerdown',start);surface.removeEventListener('pointerup',end);surface.removeEventListener('pointercancel',cancel);view.turnAnimation?.cancel();view.host.querySelectorAll('.reader-turn-sheet').forEach(sheet=>sheet.remove());});
}

function readerLoading(view){
 const panel=node('section','reader-loading'),title=node('p','reader-loading-title','Загрузка книги…'),counter=node('p','reader-loading-bytes','0,00 МБ'),bar=node('progress');
 panel.setAttribute('role','status');title.setAttribute('aria-live','polite');counter.setAttribute('aria-live','off');bar.setAttribute('aria-label','Загрузка книги');panel.append(title,bar,counter);view.host.append(panel);
 let last=0;
 function progress(loaded,total,force=false){
  if(view.disposed)return;if(!force&&performance.now()-last<100)return;last=performance.now();
  counter.textContent=megabytes(loaded)+(total?' / '+megabytes(Math.max(total,loaded)):'')+' МБ';
  if(total){bar.max=Math.max(total,loaded,1);bar.value=loaded;}else bar.removeAttribute('value');
 }
 return {progress,prepare:bytes=>{progress(bytes,bytes,true);title.textContent='Подготовка страниц…';bar.removeAttribute('value');},done:()=>{panel.hidden=true;},error:message=>{panel.classList.add('reader-loading-error');title.textContent=message;bar.hidden=true;}};
}
async function fetchReaderBytes(view,url,loading){
 const response=await fetch(url,{signal:view.controller.signal});
 if(!response.ok)throw Error(response.status===401?'Войдите в дневник заново.':'Не удалось получить файл. Попробуйте ещё раз.');
 const size=Number(view.file.size),length=Number(response.headers.get('Content-Length'));
 const total=(!response.headers.get('Content-Encoding')&&length>0?length:size>0?size:0);
 loading.progress(0,total,true);
 if(!response.body){const bytes=await response.arrayBuffer();loading.prepare(bytes.byteLength);return bytes;}
 const reader=response.body.getReader(),chunks=[];let loaded=0;
 try{
  while(true){const {done,value}=await reader.read();if(done)break;if(view.disposed)throw new DOMException('Просмотр закрыт','AbortError');chunks.push(value);loaded+=value.byteLength;loading.progress(loaded,total);}
 }finally{reader.releaseLock();}
 const bytes=new Uint8Array(loaded);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
 loading.prepare(loaded);return bytes.buffer;
}
function readerScale(view,{label,min,max,step,value,format,apply}){
 const row=node('div','reader-scale'),caption=node('span',null,label),readout=node('output'),minus=button('A−',()=>change(-step),'fd-secondary'),plus=button('A+',()=>change(step),'fd-secondary');
 minus.setAttribute('aria-label','Уменьшить '+label.toLowerCase());plus.setAttribute('aria-label','Увеличить '+label.toLowerCase());readout.setAttribute('aria-live','polite');
 row.append(caption,minus,readout,plus);view.actions.append(row);let pending=false;
 function draw(){readout.textContent=format(value);minus.disabled=pending||value<=min;plus.disabled=pending||value>=max;}
 async function change(delta){
  if(pending||view.disposed||view.reader?.busy||view.turning)return;pending=true;draw();
  try{const next=Math.max(min,Math.min(max,Math.round((value+delta)*100)/100));await apply(next);value=next;}
  catch(error){if(!view.disposed)view.status.textContent=error.message||'Не удалось изменить масштаб';}
  finally{pending=false;draw();}
 }
 draw();
}

function readerNotice(view,text){
 if(view.disposed)return;
 if(!view.notice){view.notice=node('div','reader-notice');view.notice.setAttribute('role','status');view.host.append(view.notice);}
 view.notice.textContent=text;view.notice.hidden=false;clearTimeout(view.noticeTimer);view.noticeTimer=setTimeout(()=>{if(view.notice)view.notice.hidden=true;},6500);
}
function readerUuid(){
 if(crypto.randomUUID)return crypto.randomUUID();
 const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
 return [...bytes].map((b,i)=>([4,6,8,10].includes(i)?'-':'')+b.toString(16).padStart(2,'0')).join('');
}
async function saveReaderBookmark(body){
 try{return await post('personal',body);}catch(error){
  if(error.status===403){const current=await api('me');if(current.csrf&&current.csrf!==csrf){csrf=current.csrf;return post('personal',body);}}
  if(error.status===401)throw Error('Сессия закончилась. Закройте книгу, войдите заново и сохраните закладку.');throw error;
 }
}
function retainReaderFile(view,bytes){
 const ext=(view.file.filename||'').split('.').pop().toLowerCase();
 const mime={doc:'application/msword',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',pdf:'application/pdf',rtf:'application/rtf',txt:'text/plain',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg'};
 view.originalFile=new File([bytes],view.file.filename||'Книга',{type:mime[ext]||'application/octet-stream'});
}
function readerDownload(view,event){event.preventDefault();if(!view.disposed)readerDirectDownload(view);}
function readerDirectDownload(view){
 if(!view.originalFile){readerNotice(view,'Дождитесь загрузки книги.');return;}
 const url=URL.createObjectURL(view.originalFile),link=node('a');link.href=url;link.download=view.originalFile.name;link.hidden=true;view.host.append(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),60000);readerNotice(view,'Скачивание передано браузеру. Проверьте его загрузки.');
}
async function readPdfBook(view,bytes,content,status){
 const pdfjs=await import('/static/vendor/pdfjs/build/pdf.min.mjs');if(view.disposed)return;
 pdfjs.GlobalWorkerOptions.workerSrc='/static/vendor/pdfjs/build/pdf.worker.min.mjs';
 view.pdfTask=pdfjs.getDocument({data:new Uint8Array(bytes),isEvalSupported:false,cMapUrl:'/static/vendor/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/static/vendor/pdfjs/standard_fonts/',wasmUrl:'/static/vendor/pdfjs/wasm/'});
 const pdf=await view.pdfTask.promise;if(view.disposed)return;
 let number=1,rendering=false,textMode=true,textSize=18;
 try{const saved=Number(localStorage.getItem('fgu-reader-text-size'));if(saved>=10&&saved<=40)textSize=saved;}catch{}
 const holder=node('div','pdf-reading-page'),modes=node('div','pdf-reading-modes'),textButton=button('Текст',()=>mode(true)),originalButton=button('Оригинал',()=>mode(false));modes.append(textButton,originalButton);view.actions.append(modes);content.append(holder);
 const pager=readerNavigation(view,pdf.numPages,render);
 view.reader={mode:'pdf',current:1,total:pdf.numPages,busy:false,choose:pager.choose};readerBookmarks(view);
 readerScale(view,{label:'Размер текста',min:10,max:40,step:2,value:textSize,format:value=>value+' px',apply:async value=>{
  if(!textMode){await mode(true);if(!textMode)throw Error('В скане нет текста для изменения размера.');}
  const top=view.scroller.scrollTop,ratio=top/Math.max(1,view.scroller.scrollHeight-view.scroller.clientHeight);
  textSize=value;holder.style.setProperty('--reader-text-size',value+'px');view.scroller.scrollTop=ratio*Math.max(0,view.scroller.scrollHeight-view.scroller.clientHeight);
  try{localStorage.setItem('fgu-reader-text-size',String(value));}catch{}
 }});
 function controls(){textButton.setAttribute('aria-pressed',String(textMode));originalButton.setAttribute('aria-pressed',String(!textMode));view.host.classList.toggle('reader-original-mode',!textMode);}
 async function mode(value){if(rendering||view.turning||textMode===value)return;const previous=textMode;textMode=value;try{await render(number);}catch(error){textMode=previous;controls();throw error;}}
 async function render(requested){
  if(view.disposed||rendering)return;rendering=true;pager.set(pdf.numPages,number,true);textButton.disabled=true;originalButton.disabled=true;
  try{
   status.textContent='Подготовка страницы '+requested+'…';const page=await pdf.getPage(requested);if(view.disposed)return;
   let article=null;
   if(textMode){
    const data=await page.getTextContent();if(view.disposed)return;
    const items=data.items.filter(item=>typeof item.str==='string');
    if(items.some(item=>item.str.trim())){
     article=node('article','document-page pdf-text-page');article.setAttribute('aria-label','Текст страницы '+requested+' из '+pdf.numPages);let line='';
     for(const item of items){line+=(line&&!line.endsWith(' ')?' ':'')+item.str;if(item.hasEOL&&line.trim()){article.append(node('p',null,line.trim()));line='';}}
     if(line.trim())article.append(node('p',null,line.trim()));
    }else{textMode=false;readerNotice(view,'На этой странице нет текстового слоя: это скан или изображение. Показан оригинал; увеличение букв отдельно требует распознавания текста.');}
   }
   if(article){holder.style.setProperty('--reader-text-size',textSize+'px');holder.replaceChildren(article);}
   else{
    const natural=page.getViewport({scale:1}),width=Math.max(240,Math.min(content.clientWidth,1400)),density=Math.min(devicePixelRatio||1,2),viewport=page.getViewport({scale:Math.min(width/natural.width*density,Math.sqrt(8000000/(natural.width*natural.height)))});
    const canvas=node('canvas');canvas.width=Math.floor(viewport.width);canvas.height=Math.floor(viewport.height);canvas.style.width=width+'px';canvas.setAttribute('role','img');canvas.setAttribute('aria-label','Страница '+requested+' из '+pdf.numPages);
    view.renderTask=page.render({canvasContext:canvas.getContext('2d'),viewport});await view.renderTask.promise;if(view.disposed)return;holder.replaceChildren(canvas);
   }
   number=requested;view.scroller.scrollTop=0;status.textContent='';controls();
  }catch(error){if(!view.disposed){readerNotice(view,'Не удалось открыть страницу. Повторите переход.');throw error;}}
  finally{rendering=false;if(!view.disposed){pager.set(pdf.numPages,number);textButton.disabled=false;originalButton.disabled=false;}}
 }
 let timer;const resize=()=>{if(!textMode){clearTimeout(timer);timer=setTimeout(()=>render(number).catch(()=>{}),150);}};window.addEventListener('resize',resize);view.cleanups.push(()=>{clearTimeout(timer);window.removeEventListener('resize',resize);});
 controls();await render(1);
}
