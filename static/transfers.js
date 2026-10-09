const activeUploads=new Set();
let fileView=null;
function megabytes(bytes){return (bytes/1024/1024).toLocaleString(uiLocale(),{minimumFractionDigits:2,maximumFractionDigits:2});}
function attachUpload(form,{file,title,scope,item,submit,refresh}){
 const panel=node('div','upload-progress'),label=node('p'),meter=node('progress'),state=node('p','muted');
 panel.hidden=true;meter.max=100;meter.value=0;meter.setAttribute('aria-label','Загрузка файла');
 state.setAttribute('role','status');const cancel=button('Отменить загрузку',()=>current?.abort());
 panel.append(label,meter,state,cancel);form.append(panel);let current=null;
 form.onsubmit=async event=>{
  event.preventDefault();if(current)return;const selected=file.files[0];if(!selected)return;
  if(selected.size>=100*1024*1024-65536){fail(Error('Выберите файл меньше 100 МБ.'));return;}
  panel.hidden=false;panel.classList.add('is-active');cancel.hidden=false;meter.value=0;
  label.textContent='0,00 / '+megabytes(selected.size)+' МБ';state.textContent='Загрузка файла…';
  submit.disabled=true;file.disabled=true;title.disabled=true;
  const body=new FormData();body.set('file',selected);body.set('title',title.value);body.set('scope',scope);body.set('item',item);
  try{
   await new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();current=xhr;activeUploads.add(xhr);
    xhr.open('POST','/api/files');xhr.setRequestHeader('X-CSRF-Token',csrf);xhr.timeout=10*60*1000;
    xhr.upload.onprogress=e=>{
     if(e.lengthComputable){const ratio=Math.min(1,e.loaded/e.total);meter.value=ratio*100;label.textContent=megabytes(selected.size*ratio)+' / '+megabytes(selected.size)+' МБ';}
     else meter.removeAttribute('value');
    };
    xhr.upload.onload=()=>{meter.value=100;label.textContent=megabytes(selected.size)+' / '+megabytes(selected.size)+' МБ';state.textContent='Файл передан. Сохранение на сервере…';};
    xhr.onload=()=>{let result;try{result=JSON.parse(xhr.responseText);}catch{}
     if(xhr.status>=200&&xhr.status<300&&result?.ok)resolve();
     else reject(Error(result?.error||(xhr.status===413?'Максимальный размер файла — 100 МБ.':'Сервер не подтвердил сохранение. Попробуйте ещё раз.')));
    };
    xhr.onerror=()=>reject(Error('Соединение прервано. Загрузка не подтверждена.'));
    xhr.ontimeout=()=>reject(Error('Время загрузки истекло. Проверьте соединение.'));
    xhr.onabort=()=>reject(Object.assign(Error('Загрузка отменена.'),{name:'AbortError'}));
    xhr.send(body);
   });
   meter.value=100;label.textContent=megabytes(selected.size)+' / '+megabytes(selected.size)+' МБ';state.textContent='Файл загружен';
   form.reset();delete form.dataset.dirty;
   try{await refresh();}catch{state.textContent='Файл сохранён. Обновите список, чтобы увидеть его.';}
  }catch(error){state.textContent=error.message;meter.value=0;}
  finally{activeUploads.delete(current);current=null;submit.disabled=false;file.disabled=false;title.disabled=false;cancel.hidden=true;panel.classList.remove('is-active');}
 };
}
function closeFile(){
 if(!fileView)return;const view=fileView;fileView=null;view.dispose();
 page=view.page;root.dataset.page=page;screen.replaceChildren(...view.nodes);updateBack();window.scrollTo(0,view.scroll);
 view.focus?.focus({preventScroll:true});
}
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&fileView){event.preventDefault();closeFile();}});
async function openFile(file){
 if(fileView)closeFile();
 const view={file,page,nodes:[...screen.childNodes],scroll:window.scrollY,focus:document.activeElement,controller:new AbortController(),urls:[],disposed:false,pdfTask:null,renderTask:null,bodyOverflow:document.body.style.overflow,cleanups:[]};
 view.dispose=()=>{view.disposed=true;clearTimeout(view.noticeTimer);view.originalFile=null;for(const cleanup of view.cleanups)cleanup();view.cancelDocument?.();view.controller.abort();document.body.style.overflow=view.bodyOverflow;try{tg?.BackButton?.offClick(closeFile);tg?.BackButton?.hide();}catch{}view.renderTask?.cancel();if(view.pdfTask)Promise.resolve(view.pdfTask.destroy()).catch(()=>{});for(const url of view.urls)URL.revokeObjectURL(url);};
 fileView=view;page='file';root.dataset.page='file';updateBack();screen.replaceChildren();
 const host=node('section','fd-detail-page file-viewer'),toolbar=node('div','file-toolbar'),content=node('div','file-content'),status=node('p','muted','Подготовка просмотра…');
 status.setAttribute('role','status');
 const close=button('← Закрыть файл',closeFile),download=node('a','fd-secondary reader-download','Скачать');close.setAttribute('aria-label','Закрыть файл');
 download.href='/api/files/'+encodeURIComponent(file.id);download.download=file.filename;download.onclick=event=>readerDownload(view,event);
 const scroller=node('div','file-scroller');scroller.setAttribute('role','region');scroller.setAttribute('aria-label','Чтение файла');
 view.host=host;view.scroller=scroller;view.status=status;view.actions=node('div','reader-bookmark-bar');view.actions.append(download);const caption=node('span','reader-caption',file.title);caption.title=file.filename;toolbar.append(close,caption,readerFullscreen(view));scroller.append(node('h1',null,file.title),node('p','muted',file.filename),status,content);host.append(toolbar,view.actions,scroller);screen.append(host);window.scrollTo(0,0);document.body.style.overflow='hidden';close.focus({preventScroll:true});
 try{if(tg?.initData){tg.BackButton?.onClick(closeFile);tg.BackButton?.show();}}catch{}
 const ext=(file.filename||'').split('.').pop().toLowerCase();
 if(['pdf','doc','docx','rtf'].includes(ext)){readerPhoneMode(view);view.setReadingMode(false);readerSwipes(view);}
 const types={png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp',gif:'image/gif',mp4:'video/mp4',webm:'video/webm',mp3:'audio/mpeg',m4a:'audio/mp4',ogg:'audio/ogg',wav:'audio/wav'};
 if(!types[ext]&&!['pdf','txt','csv','md','doc','docx','rtf'].includes(ext)){download.onclick=null;status.textContent='Для этого формата пока нет просмотра внутри дневника. Нажмите «Закрыть файл», чтобы вернуться.';return;}
 const loading=readerLoading(view);
 try{
  const bytes=await fetchReaderBytes(view,download.href,loading);if(view.disposed)return;retainReaderFile(view,bytes);
  if(['doc','docx','rtf'].includes(ext)){await readWordDocument(view,bytes,content,status);
  }else if(ext==='pdf'){
   await readPdfBook(view,bytes,content,status);
  }else if(['txt','csv','md'].includes(ext)){
   content.append(node('pre',null,new TextDecoder().decode(bytes.slice(0,1024*1024))));status.textContent=bytes.byteLength>1024*1024?'Показан первый 1 МБ документа.':'';
  }else{
   const type=types[ext],url=URL.createObjectURL(new Blob([bytes],{type}));view.urls.push(url);
   const media=node(type.startsWith('image/')?'img':type.startsWith('video/')?'video':'audio');
   if(media.tagName==='IMG')media.alt=file.title;else media.controls=true;
   media.onerror=()=>{if(!view.disposed)status.textContent='Этот файл не поддерживается браузером. Нажмите «Закрыть файл», чтобы вернуться.';};
   media.src=url;content.append(media);status.textContent='';
  }
 loading.done();
 }catch(error){if(!view.disposed){status.textContent=error.name==='PasswordException'?'PDF защищён паролем: просмотр внутри дневника недоступен.':error.message||'Просмотр недоступен. Нажмите «Закрыть файл», чтобы вернуться.';loading.error(status.textContent);}}
}
