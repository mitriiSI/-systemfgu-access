/* A small private popover. It only receives timetable metadata from the server. */
function comparisonDateLabel(value,reference){
 const day=new Date(value+'T12:00:00Z'),base=new Date(reference+'T12:00:00Z'),difference=Math.round((day-base)/86400000);
 if(!Number.isFinite(difference)||difference===0)return '';
 const relative=new Intl.RelativeTimeFormat(uiLocale(),{numeric:'auto'}).format(difference,'day');
 const calendar=day.toLocaleDateString(uiLocale(),{day:'numeric',month:'long',...(day.getUTCFullYear()!==base.getUTCFullYear()?{year:'numeric'}:{}),timeZone:'UTC'});
 return relative.charAt(0).toLocaleUpperCase(uiLocale())+relative.slice(1)+' · '+calendar;
}
function mountGroupComparison(host){
 if(!me?.group_comparison)return;
 const region=node('aside','group-comparison'),toggle=button('',()=>setOpen(panel.hidden),'comparison-toggle'),panel=node('section','comparison-panel');
 const text=node('span','comparison-summary'),chevron=icon('forward');chevron.classList.add('comparison-chevron');toggle.append(text,chevron);
 const controls=node('div','comparison-controls'),gear=iconButton('gear','Подпись и уведомления дополнительного расписания',()=>go('comparison-settings')),note=node('div','comparison-note');gear.classList.add('comparison-settings-button');note.hidden=true;note.dataset.noTranslate='';
 toggle.setAttribute('aria-label','Дополнительное расписание');toggle.setAttribute('aria-expanded','false');
 panel.hidden=true;panel.id='group-comparison-panel';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Дополнительное расписание');toggle.setAttribute('aria-controls',panel.id);
 const dateHint=node('time','comparison-date-hint');dateHint.hidden=true;dateHint.dataset.noTranslate='';
 controls.append(toggle,gear);region.append(controls,dateHint,note,panel);host.prepend(region);host.classList.add('has-comparison');
 const commonFirst=Boolean(me.group_comparison_admin);
 let data,week=false,date=selectedDay,job=null,loadedAt=0,requestId=0,disposed=false,onlyCommon=commonFirst,noteTimer=null;
 const close=button('×',()=>setOpen(false),'comparison-close');close.setAttribute('aria-label','Закрыть дополнительное расписание');
 const toolbar=node('div','comparison-toolbar'),label=node('strong'),dateInput=node('input','fd-input comparison-date');dateInput.type='date';dateInput.value=date;dateInput.setAttribute('aria-label','Дата дополнительного расписания');
 const filter=button('Все пары',()=>setFilter(!onlyCommon),'comparison-filter');
 toolbar.append(label,filter,close);const modes=node('div','comparison-modes'),dayButton=button('День',()=>setMode(false)),weekButton=button('Неделя',()=>setMode(true));
 const prev=iconButton('back','Предыдущая дата дополнительного расписания',()=>move(-1)),next=iconButton('forward','Следующая дата дополнительного расписания',()=>move(1));modes.append(dayButton,weekButton);
 const dates=node('div','comparison-dates');dates.append(prev,dateInput,next);const lessons=node('div','comparison-lessons'),status=node('p','comparison-status');status.setAttribute('role','status');
 panel.append(toolbar,modes,dates,lessons,status);
 function setOpen(open){
  panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open));
  if(open){draw();fitPanel();refresh(true);if(!matchMedia('(prefers-reduced-motion: reduce)').matches)panel.animate([{opacity:0,transform:'translateY(-5px) scale(.98)'},{opacity:1,transform:'translateY(0) scale(1)'}],{duration:220,easing:'cubic-bezier(.2,.7,.2,1)'});}
  else{if(panel.contains(document.activeElement))toggle.focus({preventScroll:true});if(date!==selectedDay){date=selectedDay;dateInput.value=date;refresh(true);}}
 }
 function fitPanel(){
  if(panel.hidden)return;const box=region.getBoundingClientRect(),below=innerHeight-box.bottom-96,above=box.top-60,up=below<180&&above>below;
  panel.classList.toggle('opens-up',up);panel.style.maxHeight=Math.max(120,Math.min(480,innerHeight*.55,up?above:below))+'px';
 }
 function move(step){date=addDays(date,step*(week?7:1));dateInput.value=date;refresh(true);}
 function setMode(value){week=value;draw();refresh(true);}
 function setFilter(value){if(onlyCommon===value)return;onlyCommon=value;draw();fitPanel();if(!matchMedia('(prefers-reduced-motion: reduce)').matches)text.animate([{opacity:.4,transform:'translateX('+(value?'8':'-8')+'px)'},{opacity:1,transform:'translateX(0)'}],{duration:180,easing:'ease-out'});}
 function stateOf(lesson){const clock=data.now.slice(11,16);return lesson.common?'common':lesson.date===data.today&&lesson.start<=clock&&clock<lesson.end?'live':lesson.date===data.today&&lesson.start>clock?'next':'idle';}
 function swipe(element){
  let gesture=null,suppressClick=false;
  element.addEventListener('pointerdown',event=>{suppressClick=false;if(event.isPrimary&&event.button===0)gesture={id:event.pointerId,x:event.clientX,y:event.clientY};},{passive:true});
  element.addEventListener('pointermove',event=>{if(!gesture||gesture.id!==event.pointerId)return;const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y;if(Math.abs(dx)>12&&Math.abs(dx)>Math.abs(dy)*1.3&&!element.hasPointerCapture(event.pointerId))element.setPointerCapture(event.pointerId);},{passive:true});
  element.addEventListener('pointerup',event=>{if(!gesture||gesture.id!==event.pointerId)return;const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y;gesture=null;if(Math.abs(dx)>30&&Math.abs(dx)>Math.abs(dy)*1.3){suppressClick=true;setFilter(commonFirst?dx>0:dx<0);setTimeout(()=>suppressClick=false,400);}},{passive:true});
  element.addEventListener('pointercancel',()=>gesture=null,{passive:true});
  element.addEventListener('click',event=>{if(suppressClick){event.preventDefault();event.stopImmediatePropagation();suppressClick=false;}},true);
 }
 swipe(toggle);swipe(lessons);
 dateInput.onchange=()=>{if(/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)){date=dateInput.value;refresh(true);}};
 function brief(){
  text.replaceChildren();dateHint.textContent=data?comparisonDateLabel(date,data.today):'';dateHint.hidden=!dateHint.textContent;dateHint.dateTime=date;
  if(!data){text.append(node('span',null,onlyCommon?'Общие пары':'Все пары'),node('small',null,'Загрузка…'));return;}
  const all=data.days.find(day=>day.date===date)?.lessons||[],items=all.filter(lesson=>!onlyCommon||lesson.common),who=data.preferences.label;
  const mode=onlyCommon?'Общие пары':'Все пары',title=who?who+' · '+mode.toLocaleLowerCase('ru'):mode;text.append(node('span','comparison-brief-heading',title));
  toggle.dataset.state=onlyCommon&&items.length?'common':items.some(l=>stateOf(l)==='live')?'live':items.some(l=>stateOf(l)==='next')?'next':items.some(l=>l.common)?'common':'idle';
  for(const lesson of items){
   const row=node('span','comparison-brief-row');row.dataset.state=stateOf(lesson);row.title=lesson.title+(lesson.common?' · общая пара':'');
   row.append(node('time',null,lesson.start+'–'+lesson.end),node('small',null,lesson.room||'Место не указано'));text.append(row);
  }
  if(!items.length)text.append(node('small',null,data.syncing&&!data.has_cache?'Загрузка…':onlyCommon?'Общих пар нет':'Нет сохранённых пар'));
  toggle.setAttribute('aria-label',title+'. '+(dateHint.textContent?dateHint.textContent+'. ':'')+items.map(l=>l.start+'–'+l.end+' · '+l.room+(l.common?' · общая пара':'')).join('; ')+'. Раскрыть расписание. '+(commonFirst?'Свайп влево — все пары, вправо — общие.':'Свайп влево — общие пары, вправо — все.'));
 }
 function draw(){
  brief();filter.textContent=onlyCommon?'Общие':'Все пары';filter.setAttribute('aria-pressed',String(onlyCommon));dayButton.setAttribute('aria-pressed',String(!week));weekButton.setAttribute('aria-pressed',String(week));
  if(!data){lessons.textContent='Загружаем расписание…';return;}
  label.textContent=data.preferences.label;lessons.replaceChildren();
  for(const day of data.days){
   const section=node('section','comparison-day');if(week)section.append(node('h3',null,new Date(day.date+'T12:00:00Z').toLocaleDateString(uiLocale(),{weekday:'short',day:'numeric',month:'short',timeZone:'UTC'})));
   const visible=day.lessons.filter(lesson=>!onlyCommon||lesson.common);
   if(!visible.length)section.append(node('p','muted',data.syncing&&!data.has_cache?'Загружаем…':onlyCommon?'Общих пар нет':'Нет сохранённых занятий'));
   for(const lesson of visible){
    const row=node('div','comparison-lesson'+(lesson.common?' comparison-common':'')),meta=node('div','comparison-lesson-meta');
    const clock=data.now.slice(11,16),live=lesson.date===data.today&&lesson.start<=clock&&clock<lesson.end,next=lesson.date===data.today&&lesson.start>clock;row.dataset.state=stateOf(lesson);
    meta.append(node('time',null,lesson.start+'–'+lesson.end),node('span',null,lesson.room||'Место не указано'));
    row.append(meta,node('p','comparison-subject',lesson.title));
    const stateLabel=[lesson.common?'Общая пара':'',live?'Сейчас':next?'Далее':''].filter(Boolean).join(' · ');
    if(stateLabel)row.append(node('span','comparison-state-badge',stateLabel));
    if(lesson.teachers.length){const teacher=node('p','comparison-teachers',lesson.teachers.join(' · '));teacher.dataset.personName='';row.append(teacher);}
    section.append(row);
   }
   lessons.append(section);
  }
  drawNote();
 }
 function drawNote(){
  clearTimeout(noteTimer);note.replaceChildren();note.hidden=!data.note;if(!data.note)return;
  const copy=node('p','comparison-note-copy',data.note.body);note.append(copy);
  const more=button('Ещё',()=>{const expanded=note.classList.toggle('is-expanded');more.textContent=expanded?'Свернуть':'Ещё';more.setAttribute('aria-expanded',String(expanded));},'comparison-note-more');more.setAttribute('aria-expanded',String(note.classList.contains('is-expanded')));more.textContent=note.classList.contains('is-expanded')?'Свернуть':'Ещё';note.append(more);
  requestAnimationFrame(()=>{if(!disposed)more.hidden=copy.scrollHeight<=copy.clientHeight&&!note.classList.contains('is-expanded');});
  noteTimer=setTimeout(()=>{note.hidden=true;note.replaceChildren();},Math.max(0,data.note.expires*1000-Date.parse(data.now)));
 }
 async function refresh(force=false){
  if(disposed||!host.isConnected||!me?.group_comparison)return;
  if(job){await job;if(date!==data?.selected_date||week!==data?.week)refresh(true);return;}
  if(!force&&Date.now()-loadedAt<30000&&date===data?.selected_date&&week===data?.week)return;
  const selected=date,mode=week,generation=loginGeneration,version=++requestId;
  job=(async()=>{try{const result=await api('group-comparison?date='+encodeURIComponent(selected)+'&week='+(mode?'1':'0'));if(disposed||!host.isConnected||generation!==loginGeneration||version!==requestId)return;data={...result,selected_date:selected,week:mode};loadedAt=Date.now();status.textContent='';draw();}catch(error){if(host.isConnected){status.textContent=error.message;text.replaceChildren(node('span',null,onlyCommon?'Общие пары':'Все пары'),node('small',null,'Нет соединения'));}}})();
  try{await job;}finally{job=null;}
  if(date!==selected||week!==mode)refresh(true);
 }
 function outside(event){if(!region.contains(event.target)&&!panel.hidden)setOpen(false);}
 function escape(event){if(event.key==='Escape'&&!panel.hidden){event.preventDefault();setOpen(false);}}
 document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
 window.addEventListener('resize',fitPanel,{passive:true});
 const timer=setInterval(()=>{if(!document.hidden)refresh();},30000);
 const lifecycle=new MutationObserver(()=>{if(!host.isConnected){disposed=true;clearInterval(timer);clearTimeout(noteTimer);document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);window.removeEventListener('resize',fitPanel);lifecycle.disconnect();}});lifecycle.observe(host.parentNode,{childList:true});
 host.groupComparison={refresh:()=>{if(panel.hidden){date=selectedDay;dateInput.value=date;}refresh();},open:()=>setOpen(true)};
 brief();refresh();
 if(new URLSearchParams(location.search).get('compare')==='1')setOpen(true);
}
function refreshGroupComparison(host){host.groupComparison?.refresh();}

async function comparisonSettingsPage(host){
 if(!me?.group_comparison){host.append(node('p',null,'Нет доступа'));return;}
 host.classList.add('comparison-settings-page');host.append(node('h1',null,'Дополнительное расписание'));
 const data=await api('group-comparison');if(!host.isConnected)return;
 const section=profilePanel(host,'Подпись и уведомления','comparison-preferences'),form=node('form','comparison-form'),prefs=data.preferences;
 const signature=inputField(form,'Своя подпись для окна');signature.value=prefs.label;signature.maxLength=60;signature.placeholder='Можно оставить пустым';signature.dataset.noTranslate='';
 form.append(node('p','muted','Подпись видна только вам. Номер группы в заголовок окна не добавляется.'));
 function check(title,checked){const line=node('label','comparison-check'),input=node('input');input.type='checkbox';input.checked=checked;line.append(input,node('span',null,title));form.append(line);return input;}
 let common,other,offsets,channels={};
 if(data.integrated_notifications){
  const hint=node('p','muted','Общие занятия отмечаются в обычных напоминаниях Telegram, MAX и сайта.');form.append(hint);
  const notice=node('p','comparison-notice','Общая пара с 107))');notice.dataset.noTranslate='';form.append(notice,button('Основные настройки уведомлений',()=>go('profile'),'fd-secondary'));
 }else{
  form.append(node('h3',null,'О каких парах напоминать'));common=check('Общие пары',prefs.notify_common);other=check('Остальные пары группы',prefs.notify_other);
  offsets=offsetPicker(form,'Когда напоминать',data.offset_choices,prefs.offsets);
  form.append(node('h3',null,'Куда присылать'));
  for(const [key,title] of [['telegram','Telegram'],['max','MAX'],['website','Уведомления сайта']])channels[key]=check(title,prefs.channels[key]);
 }
 const save=node('button','fd-primary','Сохранить подпись'+(data.integrated_notifications?'':' и уведомления')),status=node('p','comparison-status');save.type='submit';status.setAttribute('role','status');form.append(save,status);section.append(form);
 form.onsubmit=async event=>{
  event.preventDefault();save.disabled=true;status.textContent='';const value={label:signature.value};
  if(!data.integrated_notifications)Object.assign(value,{notify_common:common.checked,notify_other:other.checked,offsets:offsets.values(),channels:Object.fromEntries(Object.entries(channels).map(([key,input])=>[key,input.checked]))});
  try{await post('group-comparison',value);if(host.isConnected){delete form.dataset.dirty;status.textContent='Сохранено';}}
  catch(error){if(host.isConnected)status.textContent=error.message;}finally{save.disabled=false;}
 };
 if(data.can_message)await comparisonMessageEditor(host);
}

async function comparisonMessageEditor(host){
 const result=await api('admin/group-comparison/messages');if(!host.isConnected||!result.recipients.length)return;
 const section=profilePanel(host,'Сообщение под окном','comparison-message-editor'),form=node('form','comparison-message-form');
 const recipient=selectField(form,'У кого показывать');
 for(const item of result.recipients){const option=node('option',null,item.name);option.value=item.id;option.dataset.personName='';recipient.append(option);}
 const bodyLabel=node('label','fd-label','Короткое сообщение'),body=node('textarea','fd-input fd-textarea');body.setAttribute('aria-label','Короткое сообщение');bodyLabel.append(body);form.append(bodyLabel);body.maxLength=800;body.rows=3;body.dataset.noTranslate='';body.placeholder='Показывается, только когда вы что-то написали';
 const minutes=inputField(form,'Сколько минут показывать');minutes.type='number';minutes.min=1;minutes.max=10080;minutes.step=1;minutes.required=true;minutes.value=60;
 const presets=node('div','comparison-duration-presets');for(const [value,title] of [[60,'1 час'],[180,'3 часа'],[360,'6 часов'],[1440,'Сутки'],[10080,'Неделя']])presets.append(button(title,()=>{minutes.value=value;minutes.dispatchEvent(new Event('input',{bubbles:true}));},'fd-secondary'));form.append(presets);
 const help=node('p','muted','Сообщение видно только выбранному пользователю под его окном. Имя отправителя не показывается. После указанного срока оно исчезнет.');
 const status=node('p','comparison-status');status.setAttribute('role','status');
 const save=node('button','fd-primary','Показать сообщение'),remove=button('Убрать сообщение',()=>submit(''),'fd-secondary');save.type='submit';
 function populate(){const item=result.recipients.find(item=>item.id===Number(recipient.value));body.value=item?.note?.body||'';delete form.dataset.dirty;status.textContent=item?.note?'Видно до '+new Date(item.note.expires*1000).toLocaleString(uiLocale()):'Сообщения сейчас нет.';remove.disabled=!item?.note;}
 recipient.onchange=populate;
 async function submit(text){
  const ident=Number(recipient.value);save.disabled=remove.disabled=recipient.disabled=true;status.textContent='';
  try{const answer=await post('admin/group-comparison/messages',{recipient:ident,body:text,minutes:Number(minutes.value)});if(!host.isConnected)return;const item=result.recipients.find(item=>item.id===ident);item.note=answer.note;populate();status.textContent=answer.note?'Сообщение сохранено. Видно до '+new Date(answer.note.expires*1000).toLocaleString(uiLocale()):'Сообщение убрано.';}
  catch(error){if(host.isConnected)status.textContent=error.message;}finally{save.disabled=recipient.disabled=false;remove.disabled=!result.recipients.find(item=>item.id===ident)?.note;}
 }
 form.onsubmit=event=>{event.preventDefault();submit(body.value);};form.append(help,save,remove,status);section.append(form);populate();
}
