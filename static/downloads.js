// Keep original bytes and filename; the operating system chooses the destination.
function fileDownloadRow(file,compact=false){
 const row=node('article',compact?'lesson-file-attachment':'fd-note-entry download-file'),title=node('strong',null,file.title),meta=node('p','fd-file-metadata',(file.filename||'')+' · '+megabytes(file.size)+' MB');
 meta.dataset.noTranslate='';const status=node('p','muted'),meter=node('progress'),actions=node('div','download-actions');status.setAttribute('role','status');meter.hidden=true;
 const control=node('button',compact?'lesson-file-link':'fd-secondary',compact?undefined:'Скачать'),cancel=button('Отменить загрузку',()=>transfer?.controller.abort());control.type='button';cancel.hidden=true;
 const feedback=node('div','lesson-file-feedback');feedback.hidden=true;
 if(compact){const name=file.title||file.filename||'Файл';control.append(icon('folder'),node('span','lesson-file-name',name));control.title=name;control.setAttribute('aria-label','Сохранить или отправить файл: '+name);control.dataset.noTranslate='';feedback.append(meter,status,cancel);row.append(control,feedback);}else{actions.append(control,cancel);row.append(title,meta,actions,meter,status);}
 let prepared=null,transfer=null,maxTicket=null,choosing=false;
 const ready=compact?'Файл готов. Нажмите на файл ещё раз, чтобы сохранить или отправить.':'Файл готов. Нажмите «Скачать», чтобы выбрать приложение или папку.';
 function busy(value){control.disabled=value;control.setAttribute('aria-busy',String(value));if(!compact)control.textContent=value?'Загрузка…':'Скачать';}
 function direct(){const url=URL.createObjectURL(prepared),link=node('a');link.href=url;link.download=prepared.name;link.hidden=true;row.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);status.textContent='Скачивание передано браузеру. Проверьте его загрузки.';}
 async function choose(){
  if(choosing)return;choosing=true;
  try{
  if(inMax()){
   if(!maxTicket||maxTicket.until<Date.now()){
    const ticket=await post('max/files/'+encodeURIComponent(file.id)+'/ticket',{});maxTicket={url:ticket.url,until:Date.now()+(ticket.expires_in-10)*1000};
    status.textContent=ready;return;
   }
   const bridge=window.WebApp;
   if(!bridge?.downloadFile){status.textContent='Не удалось подключить MAX. Откройте дневник в браузере для скачивания.';return;}
   try{await bridge.downloadFile(maxTicket.url,file.filename);status.textContent='Скачивание передано MAX. Проверьте файлы на устройстве.';}catch(error){status.textContent=error.message||'Не удалось скачать файл. Попробуйте ещё раз.';}
   return;
  }
  if(navigator.share&&navigator.canShare?.({files:[prepared]})){
   try{await navigator.share({files:[prepared]});status.textContent='Файл передан в выбранное приложение.';}
   catch(error){if(error.name==='AbortError'){status.textContent='Выбор отменён. Файл готов к скачиванию.';return;}if(error.name==='NotAllowedError'){status.textContent=ready;return;}direct();}
  }else direct();
  }finally{choosing=false;}
 }
 control.onclick=async()=>{
  if(transfer||choosing)return;
  if(compact)feedback.hidden=false;
  if(prepared){try{await choose();}catch(error){status.textContent=error.message||'Не удалось сохранить файл. Попробуйте ещё раз.';}return;}
  const view={controller:new AbortController(),file,disposed:false};transfer=view;activeUploads.add(view);view.abort=()=>view.controller.abort();busy(true);cancel.hidden=false;meter.hidden=false;
  try{
   const bytes=await fetchReaderBytes(view,'/api/files/'+encodeURIComponent(file.id),{progress:(loaded,total)=>{status.textContent=megabytes(loaded)+' / '+(total?megabytes(total):'—')+' МБ';if(total){meter.max=Math.max(total,loaded);meter.value=loaded;}else meter.removeAttribute('value');},prepare:()=>{}});
   if(!control.isConnected)return;retainReaderFile(view,bytes);prepared=view.originalFile;meter.hidden=true;
   if(inMax()){
    await maxBridge();const ticket=await post('max/files/'+encodeURIComponent(file.id)+'/ticket',{});maxTicket={url:ticket.url,until:Date.now()+(ticket.expires_in-10)*1000};
    status.textContent=ready;return;
   }
   // Safari requires a fresh tap after an asynchronous download.
   if(navigator.userActivation?.isActive||!navigator.userActivation)await choose();else if(navigator.share&&navigator.canShare?.({files:[prepared]}))status.textContent=ready;else direct();
  }catch(error){status.textContent=error.name==='AbortError'?'Загрузка отменена.':error.message;meter.hidden=true;}
  finally{activeUploads.delete(view);transfer=null;busy(false);cancel.hidden=true;}
 };
 return row;
}

